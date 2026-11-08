"""Domain operations of the model investigation tools (see investigation.py).

``InvestigationTools`` is a mixin of ``DomainTools``: it uses the domain's
captured spec and state, its lock (held by ``DomainTools.execute``) and its
observation format. Every operation either returns evidence (views,
comparisons), adds a traced candidate, or records a verified claim. A refused
proposal returns ``ok: false`` with the verifier's reason, so the model can
revise it; nothing here selects a line, sets a review state or changes a gate.
"""
from __future__ import annotations

import copy
import math
from uuid import uuid4

from . import investigation as inv
from . import panel_assignment
from .draft import model_choice_guess
from .provenance import digest_object, write_json

ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
INVESTIGATION_ARGUMENTS = {
    "survey_sheet": {"phase1_only"},
    "describe_views": {"views"},
    "describe_vessel": {"description"},
    "view_region": {"region_px", "max_side_px"},
    "read_region": {"region_px", "subject"},
    "trace_corridor": {"section_id", "view_id", "path_px", "half_width_px"},
    "trace_from_point": {"section_id", "view_id", "point_px"},
    "enumerate_strokes": {"section_id", "height_m"},
    "assign_station": {"section_id", "candidate_id", "label_view_id", "label_text", "reason", "comparison_id"},
    "propose_sheet_setup": {"view", "region_px", "pixels_per_metre", "grid_spacing_m", "centreline_px",
                            "baseline_px", "x_origin_px", "x_direction", "evidence_view_id", "scale_claim",
                            "reason"},
    "compare_views": {"section_id", "candidate_id", "setup_id", "heights_m"},
}
REQUIRED = {
    "survey_sheet": set(),
    "describe_views": {"views"},
    "describe_vessel": {"description"},
    "view_region": {"region_px"},
    "read_region": {"region_px", "subject"},
    "trace_corridor": {"section_id", "view_id", "path_px", "half_width_px"},
    "trace_from_point": {"section_id", "view_id", "point_px"},
    "enumerate_strokes": {"section_id"},
    "assign_station": {"section_id", "candidate_id", "label_view_id", "label_text", "reason"},
    "propose_sheet_setup": {"view", "region_px", "pixels_per_metre", "grid_spacing_m", "evidence_view_id",
                            "scale_claim", "reason"},
    "compare_views": {"section_id", "candidate_id", "setup_id", "heights_m"},
}
READ_SUBJECTS = ("labels", "scale_bar", "dimensions", "title_block")


class ToolArgumentError(ValueError):
    pass


def _number(value, low, high) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _identifier(value, length=64) -> bool:
    return type(value) is str and 1 <= len(value) <= length and set(value) <= ID_CHARS


def _text(value, length) -> bool:
    return type(value) is str and 1 <= len(value) <= length and value.isprintable()


def _region(value) -> bool:
    return (type(value) is list and len(value) == 4 and all(_number(v, 0, 1_000_000) and v == int(v) for v in value)
            and value[2] > value[0] and value[3] > value[1])


def check_investigation_arguments(name: str, arguments: dict, spec: dict) -> None:
    """Bounds of every investigation argument, independent of the Rust contract."""
    given = {k for k, v in arguments.items() if v is not None}
    if not REQUIRED[name] <= given:
        raise ToolArgumentError("Missing required argument: " + ", ".join(sorted(REQUIRED[name] - given)) + ".")
    sections = {s.get("id") for s in spec.get("sections", []) if isinstance(s, dict)}
    a = arguments
    ok = True
    if name == "survey_sheet":
        ok &= a.get("phase1_only") is None or type(a["phase1_only"]) is bool
    if name == "describe_views":
        from .vessel_description import VIEW_KINDS
        views = a["views"]
        ok &= (type(views) is list and 1 <= len(views) <= 32 and all(
            isinstance(v, dict) and _identifier(v.get("view_id")) and v.get("kind") in VIEW_KINDS
            and _region(v.get("region_px")) for v in views))
    if name == "describe_vessel":
        from .vessel_description import valid_description
        ok &= valid_description(a["description"])
    if "region_px" in a:
        ok &= _region(a["region_px"])
    if a.get("max_side_px") is not None:
        ok &= _number(a["max_side_px"], 256, inv.MAX_VIEW_SIDE_PX)
    if name == "read_region":
        ok &= a["subject"] in READ_SUBJECTS
    if "section_id" in a:
        ok &= a["section_id"] in sections
    for key in ("view_id", "candidate_id", "label_view_id", "comparison_id", "evidence_view_id", "setup_id"):
        if a.get(key) is not None:
            ok &= _identifier(a[key])
    if name == "trace_corridor":
        path = a["path_px"]
        ok &= (type(path) is list and 2 <= len(path) <= 24
               and all(type(p) is list and len(p) == 2 and all(_number(v, 0, 4096) for v in p) for p in path)
               and _number(a["half_width_px"], 1, 64))
    if name == "enumerate_strokes" and a.get("height_m") is not None:
        ok &= _number(a["height_m"], -100, 1000)
    if name == "trace_from_point":
        point = a["point_px"]
        ok &= type(point) is list and len(point) == 2 and all(_number(v, 0, 4096) for v in point)
    if name == "assign_station":
        ok &= _text(a["label_text"], 64) and _text(a["reason"], 300)
    if name == "propose_sheet_setup":
        ok &= (a["view"] in ("body", "plan", "profile") and _number(a["pixels_per_metre"], 1e-3, 1e5)
               and _number(a["grid_spacing_m"], 1e-3, 100) and _text(a["scale_claim"], 128)
               and _text(a["reason"], 300) and a.get("x_direction") in (None, 1, -1)
               and all(a.get(k) is None or _number(a[k], 0, 1_000_000)
                       for k in ("centreline_px", "baseline_px", "x_origin_px")))
    if name == "compare_views":
        heights = a["heights_m"]
        ok &= type(heights) is list and 1 <= len(heights) <= 12 and all(_number(h, -100, 1000) for h in heights)
    if not ok:
        raise ToolArgumentError("Investigation arguments are outside their bounds or name unknown sections.")


def traced_candidate(traced: dict, source_sha: str, section_id: str, tool: str) -> dict:
    """Catalog entry of a verified traced line (see investigation.trace_in_source_corridor)."""
    cid = inv.model_candidate_id(source_sha, section_id, traced["contour_selection"], traced["z_range_m"])
    support = traced["support"]
    return {"candidate_id": cid, "hypothesis": "model_" + tool, "generated_by": [tool],
            "selectable": True, "model_traced": True,
            "source_support": {"observed_row_fraction": support["row_coverage"],
                               "max_missing_run_px": support["max_missing_run_px"],
                               "maximum_step_px_per_row": support["maximum_step_px_per_row"],
                               "long_component_support_fraction": support["long_component_support_fraction"],
                               "mean_trace_contrast": support["mean_trace_contrast"]},
            "snap": {"verifier": "engine_reread_in_tight_corridor_v1", "passed": True,
                     "vertical_range_from_ink": traced["vertical_range_from_ink"]},
            "grid_supported_hypothesis": False, "non_grid_competing_components": None,
            "contour_selection": traced["contour_selection"], "z_range_m": traced["z_range_m"],
            "identity_certified": False, **_stroke_description(traced)}


# Stroke fields that enumeration and tracing add to a candidate and a tag.
STROKE_DESCRIPTION_FIELDS = ("z_coverage_fraction", "hull_likeness", "linked_fragments", "follow_method", "warnings")


def _stroke_description(traced: dict) -> dict:
    return {k: traced[k] for k in STROKE_DESCRIPTION_FIELDS if k in traced}


# Distinct colours of enumerated strokes; tags repeat the colour.
STROKE_COLOURS = [(230, 25, 75), (60, 140, 60), (0, 90, 220), (245, 130, 48), (145, 30, 180), (0, 150, 150),
                  (200, 30, 200), (120, 100, 0), (128, 0, 0), (0, 0, 128), (170, 110, 40), (90, 90, 90)]


class InvestigationTools:
    """Model investigation operations; mixed into DomainTools."""

    # ------------------------------------------------------------ helpers
    def _source(self):
        from .ingest import _read_image
        image, details = _read_image(self.spec["source"], self.root / "input")
        return image, details, self.state["sources"]["source"]["sha256"]

    def _refused(self, error: inv.VerificationError, **values):
        return self._observation(False, "proposal_refused", error_code=error.code, message=str(error),
                                 verifier_evidence=error.evidence, **values)

    def _store_view(self, payload: bytes, meta: dict, kind: str, source_sha: str, **extra) -> dict:
        from .agent_tools import _artifact
        directory = self.root / "views"
        directory.mkdir(exist_ok=True)
        path = directory / f"{uuid4().hex}.png"
        path.write_bytes(payload)
        view_id = "view-" + digest_object({"png": payload.hex()[:4096], "box": meta["crop_box_px"],
                                           "n": len(self.state.get("views", []))})[:16]
        record = {"view_id": view_id, "kind": kind, **meta, **extra}
        self.state.setdefault("views", []).append(record)
        artifact = _artifact(path, self.task_dir, kind="model_observation", model_eligible=True,
                             evidence_kind=kind, view_id=view_id, crop_box_px=meta["crop_box_px"],
                             pixel_size=meta["pixel_size"], source_sha256=source_sha)
        return record, artifact

    def _view(self, view_id):
        return next((v for v in self.state.get("views", []) if v["view_id"] == view_id), None)

    # ------------------------------------------------------------ sheet description
    def _survey_sheet(self, phase1_only=False):
        from .vessel_description import survey_sheet
        image, _, _ = self._source()
        survey = survey_sheet(image, self.spec)
        self.state.update(sheet_survey=survey, description_phase="views", phase1_only=phase1_only)
        self._save()
        observed = self._view_region([0, 0, image.shape[1], image.shape[0]], 1024)
        observed.update(status="sheet_surveyed", sheet_survey=survey,
                        next_step="describe_views: name body, plan, profile, title_block and offsets_table regions in source pixels.")
        return observed

    def _description_view(self):
        from .vessel_description import GEOMETRY_KINDS
        pending = [v for v in self.state.get("described_views", [])
                   if v["kind"] in GEOMETRY_KINDS and not v.get("setup_id")]
        if not pending:
            self.state.update(description_phase="vessel", description_next_view=None)
            self._save()
            return {}
        named = pending[0]
        observed = self._view_region(named["region_px"], 1024)
        named["evidence_view_id"] = observed["view"]["view_id"]
        self.state.update(description_phase="setups", description_next_view={
            "view_id": named["evidence_view_id"], "named_view_id": named["view_id"],
            "kind": named["kind"], "region_px": named["region_px"]})
        self._save()
        return {"view": observed["view"], "artifacts": observed.get("artifacts", [])}

    def _describe_views(self, views):
        from .vessel_description import _region
        image, _, _ = self._source()
        from .vessel_description import warning
        records, warnings = [], []
        for view in views:
            box = _region(view["region_px"], image.shape)
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                warnings.append(warning(f"views.{view['view_id']}.region_px", view["region_px"], box,
                                        "Region has too little sheet overlap; expanded to the sheet for a new reading."))
                box = [0, 0, image.shape[1], image.shape[0]]
            records.append({**copy.deepcopy(view), "region_px": box})
        self.state["described_views"] = records
        self._save()
        crop = self._description_view()
        return self._observation(True, "views_described", warnings=warnings, described_views=copy.deepcopy(self.state["described_views"]),
                                 next_step="propose_sheet_setup for each geometry view, then describe_vessel.", **crop)

    def _describe_vessel(self, description):
        from .vessel_description import measure_description
        image, _, _ = self._source()
        setups = list(self.state.get("sheet_setups", {}).values())
        measured = measure_description(image, self.spec, description, setups)
        measured["views"] = copy.deepcopy(self.state.get("described_views", []))
        self.state.update(vessel_description=measured, description_phase="complete", description_next_view=None)
        write_json(self.root / "vessel.json", {"description": measured})
        self._save()
        return self._observation(True, "vessel_described", description=measured, warnings=measured["warnings"],
                                 message="Description recorded; warnings name doubtful fields. Continue with the first hull.")

    # ------------------------------------------------------------ views
    def _view_region(self, region_px, max_side_px=None, *, kind="region_view", subject=None):
        image, _, source_sha = self._source()
        try:
            region = inv.clip_region(region_px, image.shape[1], image.shape[0])
        except inv.VerificationError as exc:
            return self._refused(exc, sheet_size_px=[image.shape[1], image.shape[0]])
        payload, meta = inv.render_view(image, region, int(max_side_px or inv.MAX_VIEW_SIDE_PX))
        extra = {"subject": subject} if subject else {}
        record, artifact = self._store_view(payload, meta, kind, source_sha, **extra)
        self._save()
        return self._observation(True, "viewed", view=record, sheet_size_px=[image.shape[1], image.shape[0]],
                                 artifacts=[artifact],
                                 note="Pixels are attached to your next request. Readings you report are claims.")

    def _read_region(self, region_px, subject):
        return self._view_region(region_px, inv.MAX_VIEW_SIDE_PX, kind="label_read", subject=subject)

    # ------------------------------------------------------------ trace
    def _trace_corridor(self, section_id, view_id, path_px, half_width_px):
        view = self._view(view_id)
        if view is None:
            return self._refused(inv.VerificationError("unknown_view", "Draw the corridor on a view from this task."))
        width, height = view["pixel_size"]
        if any(not (0 <= p[0] <= width and 0 <= p[1] <= height) for p in path_px):
            return self._refused(inv.VerificationError("corridor_outside_view",
                                                       f"Corridor points must lie inside the {width} x {height} view."))
        if section_id not in self.state["catalog"]:
            return self._refused(inv.VerificationError("section_not_inspected",
                                                       "Inspect the section before tracing in it."))
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        image, details, source_sha = self._source()
        try:
            traced = inv.corridor_trace(image, section, self.spec["source"]["file"], details, view, path_px,
                                        half_width_px)
        except inv.VerificationError as exc:
            # Show the model where its corridor lies on the sheet, so it can
            # move the corridor onto the curve it means.
            view_artifact = self._corridor_view(image, view, path_px, half_width_px, source_sha, section_id)
            self._save()
            return self._refused(exc, section_id=section_id, view=view_artifact[0], artifacts=[view_artifact[1]])
        return self._record_trace(section_id, traced, image, source_sha, "trace_corridor")

    def _trace_from_point(self, section_id, view_id, point_px):
        view = self._view(view_id)
        if view is None:
            return self._refused(inv.VerificationError("unknown_view", "Name a view from this task."))
        width, height = view["pixel_size"]
        if not (0 <= point_px[0] <= width and 0 <= point_px[1] <= height):
            return self._refused(inv.VerificationError("point_outside_view",
                                                       f"The point must lie inside the {width} x {height} view."))
        if section_id not in self.state["catalog"]:
            return self._refused(inv.VerificationError("section_not_inspected",
                                                       "Inspect the section before tracing in it."))
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        image, details, source_sha = self._source()
        try:
            traced = inv.trace_from_point(image, section, self.spec["source"]["file"], details, view, point_px)
        except inv.VerificationError as exc:
            x, y = inv.view_to_source(view, point_px)
            region = inv.clip_region([int(x) - 150, int(y) - 150, int(x) + 150, int(y) + 150],
                                     image.shape[1], image.shape[0])

            def overlay(draw, to_view):
                cx, cy = to_view(x, y)
                draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(40, 90, 220), width=2)

            payload, meta = inv.render_view(image, region, 600, overlay=overlay)
            record, artifact = self._store_view(payload, meta, "refused_point", source_sha, section_id=section_id)
            self._save()
            return self._refused(exc, section_id=section_id, view=record, artifacts=[artifact])
        return self._record_trace(section_id, traced, image, source_sha, "trace_from_point")

    def _enumerate_strokes(self, section_id, height_m=None):
        """Trace every ink stroke of the section's panel and show them with numbered tags."""
        if section_id not in self.state["catalog"]:
            return self._refused(inv.VerificationError("section_not_inspected",
                                                       "Inspect the section before tracing in it."))
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        # Sections with one ROI share the panel, also when a scan gives each
        # station a calibration that differs by a pixel (panel_assignment.panel_key).
        panel = [s for s in self.spec["sections"]
                 if panel_assignment.panel_key(s) == panel_assignment.panel_key(section)
                 and s["id"] in self.state["catalog"]]
        known = [c for c in self.state["catalog"][section_id]["candidates"] if "contour_selection" in c]
        image, details, source_sha = self._source()
        strokes, refusals = inv.enumerate_strokes(image, section, self.spec["source"]["file"], details,
                                                  height_m, known)
        tags = []
        for index, traced in enumerate(strokes, 1):
            candidate = traced_candidate(traced, source_sha, "panel", "enumerate_strokes")
            for member in panel:
                candidates = self.state["catalog"][member["id"]]["candidates"]
                if not any(c["candidate_id"] == candidate["candidate_id"] for c in candidates):
                    candidates.append(copy.deepcopy(candidate))
            rows, xs = traced["trace_rows_px"], traced["trace_xs_px"]
            tags.append({"tag": index, "candidate_id": candidate["candidate_id"], "kind": traced["kind"],
                         "top_end_px": [round(xs[0], 1), rows[0]], "bottom_end_px": [round(xs[-1], 1), rows[1]],
                         "z_range_m": traced["z_range_m"], **_stroke_description(traced)})
        # Already known lines of this section are shown too, so every tag on
        # the picture names a candidate the model can assign.
        for candidate in known:
            trace = inv.dense_trace(candidate)
            if trace is not None and len(tags) < inv.MAX_ENUMERATED_STROKES + 16:
                z_range = candidate.get("z_range_m") or [section["z_min_m"], section["z_max_m"]]
                described = inv.describe_stroke({"trace_rows_px": [int(trace[0][0]), int(trace[0][-1])],
                                                 "trace_xs_px": trace[1], "z_range_m": z_range}, section)
                tags.append({"tag": len(tags) + 1, "candidate_id": candidate["candidate_id"],
                             "kind": described["kind"],
                             "top_end_px": [round(float(trace[1][0]), 1), int(trace[0][0])],
                             "bottom_end_px": [round(float(trace[1][-1]), 1), int(trace[0][-1])],
                             "z_range_m": candidate.get("z_range_m"), "known_candidate": True,
                             "z_coverage_fraction": described["z_coverage_fraction"],
                             "hull_likeness": described["hull_likeness"]})
        # Best hull candidates first, straight rulers last; tags follow that order.
        tags.sort(key=lambda t: (t["kind"] == "straight_grid_line", -t["hull_likeness"]))
        for number, tag in enumerate(tags, 1):
            tag["tag"] = number
        traces = {t["candidate_id"]: inv.dense_trace(next(c for c in self.state["catalog"][section_id]["candidates"]
                                                          if c["candidate_id"] == t["candidate_id"]))
                  for t in tags}
        recommendation = self._panel_recommendation(panel, tags, traces)
        from .fonts import dejavu_sans
        roi = section["roi_px"]
        region = inv.clip_region(roi, image.shape[1], image.shape[0])

        def overlay(draw, to_view):
            try:
                font = dejavu_sans(16)
            except OSError:
                font = None
            for tag in tags:
                rows, xs = traces[tag["candidate_id"]]
                colour = STROKE_COLOURS[(tag["tag"] - 1) % len(STROKE_COLOURS)]
                draw.line([to_view(x, y) for x, y in zip(xs[::3], rows[::3])], fill=colour, width=2)
                for share in (0.0, 0.5):
                    i = int(share * (len(rows) - 1))
                    x, y = to_view(xs[i], rows[i])
                    text = str(tag["tag"])
                    draw.rectangle([x + 3, y - 1, x + 6 + 10 * len(text), y + 18], fill=(255, 255, 255), outline=colour)
                    draw.text((x + 5, y), text, fill=colour, font=font)

        payload, meta = inv.render_view(image, region, inv.MAX_VIEW_SIDE_PX, overlay=overlay)
        record, artifact = self._store_view(payload, meta, "enumerated_strokes", source_sha, section_id=section_id)
        self._save()
        return self._observation(True, "strokes_enumerated", section_id=section_id,
                                 panel_section_ids=[s["id"] for s in panel], strokes=tags,
                                 recommended_station_assignment=recommendation,
                                 refused_seeds=len(refusals), view=record, artifacts=[artifact],
                                 note="Each tag number is drawn twice on its stroke (top end and middle) in the "
                                      "stroke's colour. Find the stroke that carries a station label and assign its "
                                      "candidate_id to that station. Every stroke is real ink; none is an identity. Tags "
                                      "are ordered by hull_likeness (a ranking heuristic, not identity); "
                                      "straight_grid_line strokes come last.")

    def _panel_choices(self, section_ids) -> dict:
        """Candidate already chosen for each of these sections: a selection, else a model claim."""
        chosen = {sid: choice["candidate_id"] for sid, choice in self.state.get("model_choices", {}).items()}
        chosen.update(self.state["selected"])
        return {sid: cid for sid, cid in chosen.items() if sid in section_ids}

    def _panel_recommendation(self, panel, tags, traces) -> dict | None:
        """One recommended tag per station of a shared panel (panel_assignment.assign_panel).

        Adds ``recommended_for`` to each recommended tag, so the retained tag
        list keeps the hint. None for a panel of one section.
        """
        if len(panel) < 2:
            return None
        strokes = [{"candidate_id": t["candidate_id"], "rows": traces[t["candidate_id"]][0],
                    "xs": traces[t["candidate_id"]][1], "hull_likeness": t["hull_likeness"], "kind": t["kind"]}
                   for t in tags if traces.get(t["candidate_id"]) is not None]
        catalog = self.state["catalog"]
        tagged = [{"candidate_id": t["candidate_id"], "contour_selection": {
            "anchors_px": [[float(x), float(y)] for x, y in zip(*traces[t["candidate_id"]][::-1])]}}
            for t in tags if traces.get(t["candidate_id"]) is not None]
        pinned = {}
        for sid, cid in self._panel_choices({s["id"] for s in panel}).items():
            chosen = next((c for c in catalog[sid]["candidates"] if c["candidate_id"] == cid), None)
            match = chosen and next((t for t in tagged if t["candidate_id"] == cid or inv.same_ink(chosen, t)), None)
            if match:
                pinned[sid] = match["candidate_id"]
        assigned = panel_assignment.assign_panel(panel, self.spec["sections"], strokes, pinned)
        tag_of = {t["candidate_id"]: t for t in tags}
        result = {}
        for sid, item in assigned.items():
            tag = tag_of[item["candidate_id"]]
            tag.setdefault("recommended_for", []).append(sid)
            result[sid] = {"tag": tag["tag"], "candidate_id": item["candidate_id"],
                           "confidence": item["confidence"],
                           "alternative_tags": [tag_of[c]["tag"] for c in item["alternatives"]],
                           "warnings": item["warnings"]}
        return {"stations": result, "basis": panel_assignment.BASIS,
                "note": "A hint from nesting order: midship stations are outermost, end stations innermost, on "
                        "each side. Confirm with the station labels before assign_station."}

    def _assign_shared_panels(self) -> None:
        """Recommend one stroke per station for every inspected shared panel (panel_assignment.py).

        Runs once per panel; the catalog entries keep the recommendation and
        the strokes it names, so inspection and draft guesses can use them.
        """
        sections = [s for s in self.spec.get("sections", []) if isinstance(s, dict)]
        if not panel_assignment.pending_panels(sections, self.state["catalog"]):
            return
        image, details, source_sha = self._source()
        ids = {s["id"] for s in sections}
        panel_assignment.assign_shared_panels(image, sections, self.state["catalog"], self.spec["source"]["file"],
                                              details, source_sha, self._panel_choices(ids))
        self._save()

    def _record_trace(self, section_id, traced, image, source_sha, tool):
        """Add a verified traced line to the section's catalog and show it to the model."""
        entry = self.state["catalog"][section_id]
        candidate = traced_candidate(traced, source_sha, section_id, tool)
        existing = next((c for c in entry["candidates"] if inv.same_ink(c, candidate)
                         and c.get("z_range_m") == candidate["z_range_m"]), None)
        new = existing is None
        if new:
            entry["candidates"].append(candidate)
        else:
            candidate = existing
        rows, xs = traced["trace_rows_px"], traced["trace_xs_px"]
        trace_points = [(x, rows[0] + i) for i, x in enumerate(xs)]
        corridor = traced["corridor_source_px"]
        left = int(max(0, min(p[0] for p in trace_points) - 120))
        right = int(min(image.shape[1], max(p[0] for p in trace_points) + 120))
        top, bottom = int(max(0, rows[0] - 40)), int(min(image.shape[0], rows[1] + 40))
        region = inv.clip_region([left, top, right, bottom], image.shape[1], image.shape[0])

        def overlay(draw, to_view):
            path = corridor["path"]
            for sign in (-1, 1):
                draw.line([to_view(x + sign * corridor["half_width_px"], y) for x, y in path], fill=(40, 90, 220))
            draw.line([to_view(x, y) for x, y in trace_points[::2]], fill=(230, 30, 30), width=2)

        payload, meta = inv.render_view(image, region, inv.MAX_VIEW_SIDE_PX, overlay=overlay)
        record, artifact = self._store_view(payload, meta, "corridor_trace", source_sha,
                                            section_id=section_id, candidate_id=candidate["candidate_id"])
        evidence = self.root / "traces" / f"{candidate['candidate_id']}.json"
        evidence.parent.mkdir(exist_ok=True)
        write_json(evidence, {"section_id": section_id, "candidate_id": candidate["candidate_id"], **traced,
                              "source_sha256": source_sha, "identity_certified": False})
        self._save()
        return self._observation(True, "traced", section_id=section_id, candidate_id=candidate["candidate_id"],
                                 new_candidate=new, support=traced["support"], z_range_m=traced["z_range_m"],
                                 vertical_range_from_ink=traced["vertical_range_from_ink"], view=record,
                                 **_stroke_description(traced),
                                 artifacts=[artifact],
                                 note="Red: traced ink. Blue: your corridor. The line is a candidate, not an identity.")

    def _corridor_view(self, image, view, path_px, half_width_px, source_sha, section_id):
        """A view of a refused corridor (blue edges) over the sheet ink."""
        path = [inv.view_to_source(view, p) for p in path_px]
        half_width = float(half_width_px) / min(view["view_px_per_source_px"])
        xs, ys = [p[0] for p in path], [p[1] for p in path]
        region = inv.clip_region([int(min(xs) - half_width - 120), int(min(ys) - 40),
                                  int(max(xs) + half_width + 120), int(max(ys) + 40)],
                                 image.shape[1], image.shape[0])

        def overlay(draw, to_view):
            ordered = sorted(path, key=lambda p: p[1])
            for sign in (-1, 1):
                draw.line([to_view(x + sign * half_width, y) for x, y in ordered], fill=(40, 90, 220), width=2)

        payload, meta = inv.render_view(image, region, inv.MAX_VIEW_SIDE_PX, overlay=overlay)
        return self._store_view(payload, meta, "refused_corridor", source_sha, section_id=section_id)

    # ------------------------------------------------------------ assign
    def _assign_station(self, section_id, candidate_id, label_view_id, label_text, reason, comparison_id=None):
        try:
            evidence = inv.check_assignment(self.state, self.spec["sections"], section_id, candidate_id,
                                            label_view_id, label_text, comparison_id)
        except inv.VerificationError as exc:
            return self._refused(exc, section_id=section_id)
        # A station claim replaces an earlier model-authored shape of the section.
        self.state.get("authored_sections", {}).pop(section_id, None)
        choices = self.state.setdefault("model_choices", {})
        choices[section_id] = {"candidate_id": candidate_id, "reason": reason, "verifier_evidence": evidence}
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        candidates = [c for c in self.state["catalog"][section_id]["candidates"] if c.get("selectable") is True]
        guess = model_choice_guess(section, candidates, choices[section_id])
        guesses = [g for g in self.open_guesses if g["section_id"] != section_id] + [guess]
        order = {s["id"]: i for i, s in enumerate(self.spec["sections"])}
        self.state.update(guesses=sorted(guesses, key=lambda g: order[g["section_id"]]),
                          revision=self.state["revision"] + 1, validation=None, rendered_views=[])
        self._save()
        return self._observation(True, "assigned_as_open_guess", section_id=section_id, guess=copy.deepcopy(guess),
                                 message="Recorded as an open model_choice guess. Only a person can confirm it.")

    # ------------------------------------------------------------ sheet setup
    def _propose_sheet_setup(self, view, region_px, pixels_per_metre, grid_spacing_m, evidence_view_id,
                             scale_claim, reason, centreline_px=None, baseline_px=None, x_origin_px=None,
                             x_direction=None):
        if self._view(evidence_view_id) is None:
            return self._refused(inv.VerificationError("unknown_evidence_view",
                                                       "The scale evidence must name a view from this task."))
        setup = {"view": view, "region_px": region_px, "pixels_per_metre": pixels_per_metre,
                 "grid_spacing_m": grid_spacing_m, "centreline_px": centreline_px, "baseline_px": baseline_px,
                 "x_origin_px": x_origin_px, "x_direction": x_direction}
        image, _, _ = self._source()
        if self.state.get("description_phase") == "setups":
            from .vessel_description import measure_setup
            named = next((v for v in self.state.get("described_views", [])
                          if v.get("evidence_view_id") == evidence_view_id), None)
            setup["view_id"] = named["view_id"] if named else view
            record = measure_setup(image, self.spec, setup)
            setup_id = "setup-" + digest_object(record)[:16]
            record.update(setup_id=setup_id, status="open_model_choice", evidence_view_id=evidence_view_id,
                          scale_claim=scale_claim, reason=reason, identity_certified=False)
            self.state.setdefault("sheet_setups", {})[setup_id] = record
            if named:
                named["setup_id"] = setup_id
            self._save()
            crop = self._description_view()
            return self._observation(True, "setup_accepted_as_model_choice", setup=copy.deepcopy(record),
                                     warnings=record["warnings"], **crop)
        try:
            evidence = inv.check_sheet_setup(image, self.spec["sections"], setup)
        except inv.VerificationError as exc:
            return self._refused(exc)
        setup_id = "setup-" + digest_object(setup)[:16]
        record = {**setup, "region_px": evidence["region_px"], "setup_id": setup_id,
                  "status": "open_model_choice", "evidence_view_id": evidence_view_id,
                  "scale_claim": scale_claim, "reason": reason, "verifier_evidence": evidence,
                  "identity_certified": False}
        self.state.setdefault("sheet_setups", {})[setup_id] = record
        self._save()
        return self._observation(True, "setup_accepted_as_model_choice", setup=copy.deepcopy(record),
                                 message="Accepted for comparisons only. The build keeps the declared calibration.")

    # ------------------------------------------------------------ compare
    def _compare_views(self, section_id, candidate_id, setup_id, heights_m):
        setup = self.state.get("sheet_setups", {}).get(setup_id)
        candidate = next((c for c in self.state["catalog"].get(section_id, {}).get("candidates", [])
                          if c["candidate_id"] == candidate_id), None)
        if setup is None or candidate is None:
            return self._refused(inv.VerificationError("unknown_setup_or_candidate",
                                                       "Name an accepted setup and a candidate of this section."))
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        image, _, source_sha = self._source()
        try:
            result = inv.compare_with_plan(image, section, candidate, setup, heights_m)
        except inv.VerificationError as exc:
            return self._refused(exc, section_id=section_id)
        comparison_id = "compare-" + digest_object({"s": section_id, "c": candidate_id, "setup": setup_id,
                                                     "h": heights_m})[:16]
        record = {"comparison_id": comparison_id, "section_id": section_id, "candidate_id": candidate_id,
                  "setup_id": setup_id, **result}
        self.state.setdefault("comparisons", {})[comparison_id] = record
        column = result["plan_column_px"]
        left, top, right, bottom = setup["region_px"]
        region = inv.clip_region([int(column) - 150, top, int(column) + 150, bottom], image.shape[1], image.shape[0])

        def overlay(draw, to_view):
            draw.line([to_view(column, top), to_view(column, bottom)], fill=(40, 90, 220))
            for row in result["heights"]:
                if row["body_half_breadth_m"] is None:
                    continue
                y = float(setup["centreline_px"]) + row["body_half_breadth_m"] * float(setup["pixels_per_metre"])
                colour = (30, 160, 60) if row["matched"] else (230, 30, 30)
                draw.ellipse([*to_view(column - 6, y - 6), *to_view(column + 6, y + 6)], outline=colour)

        payload, meta = inv.render_view(image, region, inv.MAX_VIEW_SIDE_PX, overlay=overlay)
        view, artifact = self._store_view(payload, meta, "view_comparison", source_sha, section_id=section_id,
                                          candidate_id=candidate_id)
        self._save()
        return self._observation(True, "compared", comparison=record, view=view, artifacts=[artifact])
