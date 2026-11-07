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
from .draft import model_choice_guess
from .provenance import digest_object, write_json

ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
INVESTIGATION_ARGUMENTS = {
    "view_region": {"region_px", "max_side_px"},
    "read_region": {"region_px", "subject"},
    "trace_corridor": {"section_id", "view_id", "path_px", "half_width_px"},
    "assign_station": {"section_id", "candidate_id", "label_view_id", "label_text", "reason", "comparison_id"},
    "propose_sheet_setup": {"view", "region_px", "pixels_per_metre", "grid_spacing_m", "centreline_px",
                            "baseline_px", "x_origin_px", "x_direction", "evidence_view_id", "scale_claim",
                            "reason"},
    "compare_views": {"section_id", "candidate_id", "setup_id", "heights_m"},
}
REQUIRED = {
    "view_region": {"region_px"},
    "read_region": {"region_px", "subject"},
    "trace_corridor": {"section_id", "view_id", "path_px", "half_width_px"},
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
            return self._refused(exc, section_id=section_id)
        entry = self.state["catalog"][section_id]
        cid = inv.model_candidate_id(source_sha, section_id, traced["contour_selection"], traced["z_range_m"])
        candidate = {"candidate_id": cid, "hypothesis": "model_corridor_trace", "generated_by": ["trace_corridor"],
                     "selectable": True, "model_traced": True,
                     "source_support": {"observed_row_fraction": traced["support"]["row_coverage"],
                                        "max_missing_run_px": traced["support"]["max_missing_run_px"],
                                        "maximum_step_px_per_row": traced["support"]["maximum_step_px_per_row"],
                                        "long_component_support_fraction": traced["support"]["long_component_support_fraction"],
                                        "mean_trace_contrast": traced["support"]["mean_trace_contrast"]},
                     "snap": {"verifier": "engine_reread_in_tight_corridor_v1", "passed": True,
                              "vertical_range_from_ink": traced["vertical_range_from_ink"]},
                     "grid_supported_hypothesis": False, "non_grid_competing_components": None,
                     "contour_selection": traced["contour_selection"], "z_range_m": traced["z_range_m"],
                     "identity_certified": False}
        existing = next((c for c in entry["candidates"] if inv.same_ink(c, candidate)
                         and c.get("z_range_m") == candidate["z_range_m"]), None)
        new = existing is None
        if new:
            if sum(bool(c.get("model_traced")) for c in entry["candidates"]) >= inv.MAX_MODEL_CANDIDATES_PER_SECTION:
                return self._refused(inv.VerificationError(
                    "corridor_candidate_limit",
                    f"This section already has {inv.MAX_MODEL_CANDIDATES_PER_SECTION} traced candidates; assign or "
                    "compare existing ones."), section_id=section_id)
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
                                 artifacts=[artifact],
                                 note="Red: traced ink. Blue: your corridor. The line is a candidate, not an identity.")

    # ------------------------------------------------------------ assign
    def _assign_station(self, section_id, candidate_id, label_view_id, label_text, reason, comparison_id=None):
        try:
            evidence = inv.check_assignment(self.state, self.spec["sections"], section_id, candidate_id,
                                            label_view_id, label_text, comparison_id)
        except inv.VerificationError as exc:
            return self._refused(exc, section_id=section_id)
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
