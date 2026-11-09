"""Source-bound, typed operations for the hull reconstruction agent.

The model chooses opaque candidates, never Python or paths. In draft mode it
may also write a section's geometry (propose_section); code fairs it, checks it
and labels it ai_inferred or ai_corrected. A traced candidate is a hypothesis
about visible ink.  Selecting it remains a semantic
review obligation even when the ordinary engine can construct a valid solid.
All image/native work runs in the existing bounded worker profile.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import copy
import json
import math
import os
import re
from pathlib import Path
import stat
import sys
from uuid import uuid4

import numpy as np

from .file_lock import try_lock_exclusive
from .draft import (DRAFT_STATUS, guessed_choices, make_guesses, model_authored_guess, model_choice_guess,
                    section_sources)
from .investigation_tools import (INVESTIGATION_ARGUMENTS, InvestigationTools, ToolArgumentError,
                                  check_investigation_arguments)
from .ingest import _grid_evidence
from .isolation import DEFAULT_LIMITS, run_isolated, supervise_process
from .provenance import digest_file, digest_object, safe_relative_file, write_json
from .schema import MAX_SPEC_BYTES, is_sheet_only, load_bounded_json, loads_bounded_json, validate_spec
from . import section_authoring


DOMAIN_VERSION = "source_bound_tools_v1"
# Captured intake record of a sheet-only spec, and the spec with the sections
# materialized from the phase-1 reading (both in domain/input).
INTAKE_FILE = "intake.json"
MATERIALIZED_SPEC = "materialized_spec.json"
VIEWS = ("body", "plan", "profile", "oblique")
MAX_CANDIDATES = 10
# Most sections in one inspection call (and in one observation).
INSPECTION_BATCH = 12
# CPU limit of one non-native worker call (RLIMIT_CPU). It is not raised here.
INSPECTION_CPU_SECONDS = 45
# Estimated inspection CPU per megapixel of section ROI. Measured on the
# Gunnerus composite body plan (docs/BENCHMARK_GUNNERUS.md 7.5): a 4.18 Mpx
# whole-half-body-plan ROI needs 3.4-3.9 CPU s, and 12 such ROIs 50.4 CPU s
# (1.0 s/Mpx). Tracing cost grows with the pixels and the overlaid ink in the ROI.
INSPECTION_CPU_SECONDS_PER_MEGAPIXEL = 1.0
# A batch is filled only up to this share of the CPU limit, so drawings denser
# than the measured one still finish inside the unchanged limit.
INSPECTION_BUDGET_SHARE = 0.5
MAX_INSPECTION_BYTES = 24 * 1024 * 1024
# The fit that judges a model's section edit (keep or refuse) and ranks its
# builds: "draft_fit" (draft_fit.py: body plan, profile and half-breadth plan
# in one frame measured by code) when the task has one, else "combined_fit"
# (body plan only, in the reading's own frame). The body-plan fit ranked 75 %
# of L0 draft pairs as truth does, the three-view fit 85 % (docs/HULL_SELECTION.md).
EDIT_KEEP_FIT = "draft_fit"
SEMANTIC_FLAGS = {"human_semantic_review_required": True, "engineering_approved": False,
                  "identity_certified": False}
# Mark and revise: an edit of a section a person asked to revise is kept only
# when its ink RMS grows by at most this much (metres, or share of the old
# RMS, whichever is larger); then the whole-sheet fit decides.
REVISION_INK_TOLERANCE_M = 0.05
REVISION_INK_TOLERANCE_SHARE = 0.05


def revision_ink_worse(old_ink: dict, new_ink: dict) -> bool:
    """True when a revision edit makes its section's ink fit worse than the tolerance allows."""
    before = old_ink.get("rms_m")
    if before is None:
        return False  # No measured ink to protect: the overall fit decides.
    after = new_ink.get("rms_m")
    allowed = max(REVISION_INK_TOLERANCE_M, REVISION_INK_TOLERANCE_SHARE * before)
    return after is None or after > before + allowed


MIRRORED_HALF_NOTE = ("The curve is drawn left of the centreline (afterbody of an overlay body plan). The "
                      "panel's strokes are enumerated on the mirrored image; use enumerate_strokes or "
                      "trace_from_point on this section, or propose_section.")
# propose_section: the model writes a section's shape (section_authoring.py).
PROPOSE_SECTION_ARGUMENTS = {"section_id", "form", "basis", "replaces", "offsets_m", "fullness", "shape",
                             "beam_m", "draft_m", "bilge_radius_m", "deadrise_deg"}
PROPOSE_SECTION_DESCRIPTION = (
    "Write the shape of a section yourself when it has no usable traced curve or you judge the trace wrong. "
    "form half_breadths: offsets_m = 5-24 [height_m, half_breadth_m] pairs; blend: the two neighbouring "
    "sections blended by station position, scaled by fullness (0.5-1.5); standard_form: U or V section with "
    "beam_m, draft_m, optional bilge_radius_m and deadrise_deg. The host fairs the curve, clamps it to the "
    "declared beam and depth, shows it on the source panel and returns warnings. build_draft uses it, labelled "
    "ai_inferred (replaces 'none') or ai_corrected (replaces a traced candidate id).")
PROPOSE_SECTION_PROPERTIES = {
    "section_id": {"type": "string", "maxLength": 64},
    "form": {"type": "string", "enum": list(section_authoring.FORMS)},
    "basis": {"type": "string", "maxLength": section_authoring.MAX_BASIS_CHARS},
    "replaces": {"type": "string", "maxLength": 64},
    "offsets_m": {"type": "array", "minItems": section_authoring.MIN_OFFSETS,
                  "maxItems": section_authoring.MAX_OFFSETS,
                  "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
    "fullness": {"type": "number", "minimum": section_authoring.FULLNESS_RANGE[0],
                 "maximum": section_authoring.FULLNESS_RANGE[1]},
    "shape": {"type": "string", "enum": list(section_authoring.SHAPES)},
    "beam_m": {"type": "number"}, "draft_m": {"type": "number"},
    "bilge_radius_m": {"type": "number"}, "deadrise_deg": {"type": "number"}}


class ToolInputError(ValueError):
    """A recoverable rejected action, without arbitrary exception text."""


def _definition(name, description, properties=None, required=()):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required),
        "additionalProperties": False}}


# Station overlay artifacts a render worker may return: allowed display keys and file names.
OVERLAY_ARTIFACT_KEYS = {"station_overlay": ("panel", "section_ids", "crop_box_px", "scale"),
                         "station_overlay_sheet": ("panel_count",),
                         "station_scoreboard": ()}
OVERLAY_FILE_NAMES = {"station_overlay": re.compile(r"station-overlay-\d{2}\.png"),
                      "station_overlay_sheet": re.compile(r"station-overlay-sheet\.png"),
                      "station_scoreboard": re.compile(r"station-scoreboard\.json")}


def _artifact(path: Path, task_dir: Path, *, kind: str, **extra) -> dict:
    relative = path.relative_to(task_dir).as_posix()
    safe_relative_file(task_dir, relative)
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".json": "application/json", ".step": "model/step",
            ".stl": "model/stl"}.get(suffix, "application/octet-stream")
    sha = digest_file(path)
    # Computed fields come last, so caller-supplied extras can never replace them.
    return {**extra, "id": "artifact-" + sha[:24], "sha256": sha, "mime_type": mime,
            "path": relative, "kind": kind, "bytes": path.stat().st_size}


class DomainTools(InvestigationTools):
    """One persistent, source-bound tool domain owned by the harness controller.

    ``task_dir`` and ``spec_path`` are trusted application inputs, never tool
    arguments.  The task may be reopened after its original inputs disappear.
    The controller is responsible for its global call/token/elapsed budgets;
    this class also bounds each parser/CAD worker and serializes mutations.
    """

    def __init__(self, task_dir: Path, spec_path: Path, *, cancel_event=None):
        self.task_dir = Path(task_dir).resolve()
        self.root = self.task_dir / "domain"
        self.cancel_event = cancel_event
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("The domain directory must not be a symbolic link.")
        self.state_path = self.root / "state.json"
        if not self.state_path.exists():
            self._capture(Path(spec_path).resolve())
        self.state = load_bounded_json(self.state_path, max_bytes=MAX_INSPECTION_BYTES,
                                       max_nodes=600_000)
        if self.state.get("version") != DOMAIN_VERSION:
            raise ValueError("Unsupported domain state version.")
        self._verify_inputs()

    def _capture(self, spec_path):
        raw = spec_path.read_bytes() if spec_path.stat().st_size <= MAX_SPEC_BYTES else b""
        spec = loads_bounded_json(raw)
        if not isinstance(spec, dict):
            raise ValueError("The task requires a bounded specification object.")
        destination = self.root / "input"
        destination.mkdir(exist_ok=False)
        captured = copy.deepcopy(spec)
        sources = {}
        from .pipeline import _copy_source
        for role in ("source", "station_reference"):
            settings = captured.get(role)
            if settings is None and role == "station_reference":
                continue
            if not isinstance(settings, dict) or not isinstance(settings.get("file"), str):
                continue  # The ordinary schema validator records this gap.
            # An input document can name its sibling evidence, not unrelated
            # files on the host. The model never supplies this path.
            source = safe_relative_file(spec_path.parent, settings["file"])
            name, sha = _copy_source(source, destination, role)
            supplied = settings.get("sha256")
            if supplied is not None and supplied != sha:
                raise ValueError("Declared source hash does not match captured bytes.")
            settings.update(file=name, sha256=sha)
            sources[role] = {"file": name, "sha256": sha}
        intake = None
        if is_sheet_only(captured) and isinstance(captured["intake"].get("file"), str):
            # The intake record (pages, proposed view regions) is evidence of a
            # sheet-only spec; it is captured beside the source like the drawing.
            record = safe_relative_file(spec_path.parent, captured["intake"]["file"])
            (destination / INTAKE_FILE).write_bytes(record.read_bytes())
            intake = {"file": INTAKE_FILE, "sha256": digest_file(destination / INTAKE_FILE)}
            captured["intake"] = dict(intake)
        (destination / "submitted_spec.json").write_bytes(raw)
        write_json(destination / "spec.json", captured)
        validation = validate_spec(captured, destination, allow_sheet_only=True)
        state = {"version": DOMAIN_VERSION, "submitted_spec_sha256": digest_object(spec),
                 "input_spec_sha256": digest_file(destination / "spec.json"), "sources": sources,
                 "revision": 0, "selected": {}, "catalog": {}, "inspection_artifacts": [],
                 "builds": [], "last_valid_candidate": None, "validation": None,
                 "rendered_views": [], "input_errors": validation}
        if intake is not None:
            state.update(sheet_only=True, intake=intake)
        write_json(self.state_path, state)

    def _verify_inputs(self):
        self.revision_id  # Reject malformed checkpoint revisions before any operation.
        path = safe_relative_file(self.root, "input/spec.json")
        if digest_file(path) != self.state["input_spec_sha256"]:
            raise ValueError("Captured specification changed after task admission.")
        for item in self.state["sources"].values():
            source = safe_relative_file(self.root / "input", item["file"])
            if digest_file(source) != item["sha256"]:
                raise ValueError("Captured drawing changed after task admission.")
        if self.state.get("intake"):
            record = safe_relative_file(self.root / "input", self.state["intake"]["file"])
            if digest_file(record) != self.state["intake"]["sha256"]:
                raise ValueError("Captured intake record changed after task admission.")
        # The captured spec never changes. A sheet-only task adds the sections it
        # materialized after phase 1 (materialize.py) in a second, hashed file.
        self.captured_spec = load_bounded_json(path)
        self.spec = self.captured_spec
        if self.state.get("materialized_spec_sha256"):
            materialized = safe_relative_file(self.root / "input", MATERIALIZED_SPEC)
            if digest_file(materialized) != self.state["materialized_spec_sha256"]:
                raise ValueError("Materialized specification changed after it was written.")
            self.spec = load_bounded_json(materialized)

    @property
    def spec_path(self) -> Path:
        """The spec file whose sections the tools use (materialized when present)."""
        name = MATERIALIZED_SPEC if self.state.get("materialized_spec_sha256") else "spec.json"
        return self.root / "input" / name

    def intake_hints(self) -> list[dict]:
        """Proposed view regions of the source page from the intake record, if any."""
        if not self.state.get("intake"):
            return []
        record = load_bounded_json(self.root / "input" / self.state["intake"]["file"])
        page = next((p for p in record.get("pages", []) if p.get("page_id") == record.get("spec_page_id")), None)
        return [r for r in (page or {}).get("regions", []) if isinstance(r, dict) and r.get("label") != "skip"]

    def _materialize_sections(self):
        """Write declared sections for a sheet-only task from its phase-1 reading."""
        from .materialize import materialize_sections, materialized_spec
        image, _, _ = self._source()
        made = materialize_sections(image, self.captured_spec, self.state, self.intake_hints())
        spec, gaps = materialized_spec(self.captured_spec, made["sections"], self.root / "input")
        destination = self.root / "input" / MATERIALIZED_SPEC
        write_json(destination, spec)
        self.state.update(materialized_spec_sha256=digest_file(destination),
                          materialization=made["report"], materialization_gaps=gaps[:32])
        self.spec = spec
        self._save()
        return made["report"]

    @property
    def revision_id(self):
        revision = self.state.get("revision")
        if type(revision) is not int or not 0 <= revision <= 99_999_999:
            raise ValueError("Domain revision must be an exact bounded nonnegative integer.")
        return f"r{revision:04d}"

    @property
    def open_guesses(self) -> list[dict]:
        """Open draft guesses. Absent in tasks created before drafts existed."""
        return self.state.get("guesses") or []

    @property
    def generation_id(self):
        identity = {"source": self.state["input_spec_sha256"], "selected": self.state["selected"]}
        # Open guesses are part of the identity, so a draft generation never
        # equals the generation that a person later confirms. Without guesses
        # the identity (and every older task) is unchanged.
        if self.open_guesses:
            identity["guessed"] = guessed_choices(self.open_guesses)
        return "generation-" + digest_object(identity)[:24]

    def _save(self):
        write_json(self.state_path, self.state)

    def describe(self) -> dict:
        sections = [{"id": s.get("id"), "x_m": s.get("x_m"), "roi_px": s.get("roi_px"),
                     "selected_candidate_id": self.state["selected"].get(s.get("id")),
                     "catalog_available": s.get("id") in self.state["catalog"],
                     "inspection_failure": self.state["catalog"].get(s.get("id"), {}).get("inspection_failure"),
                     "inspected": s.get("id") in self.state["catalog"] and not
                                  self.state["catalog"][s.get("id")].get("inspection_failure")}
                    for s in self.spec.get("sections", []) if isinstance(s, dict)]
        current = next((b for b in reversed(self.state["builds"])
                        if b["generation_id"] == self.generation_id and b["revision_id"] == self.revision_id), None)
        ordered = sorted(self.state["catalog"].values(),
                         key=lambda s: (s["section_id"] in self.state["selected"], s["section_id"]))
        inspected = [{"section_id": item["section_id"],
                      "selected_candidate_id": self.state["selected"].get(item["section_id"]),
                      "grid_evidence": {k: item["grid_evidence"].get(k) for k in
                                        ("lattice_detected", "unique_non_grid_candidate_id", "non_grid_competing_components")},
                      "candidates": [{k: c[k] for k in ("candidate_id", "hypothesis", "selectable")}
                                     for c in item["candidates"]]}
                     for item in ordered[:INSPECTION_BATCH]]
        return {"domain_version": DOMAIN_VERSION, "revision_id": self.revision_id,
                "source_manifest_sha256": digest_object({"spec_sha256": self.state["input_spec_sha256"],
                                                           "sources": self.state["sources"]}),
                "generation_id": self.generation_id, "sections": sections,
                "section_count": len(sections), "selected_count": len(self.state["selected"]),
                "remaining_count": len(sections) - len(self.state["selected"]),
                "catalog_ready": bool(sections) and all(s["catalog_available"] for s in sections),
                "failed_inspection_section_ids": [s["id"] for s in sections if s["inspection_failure"]],
                "inspected_sections": inspected, "inspected_section_count": len(ordered),
                "inspected_sections_truncated": len(ordered) > INSPECTION_BATCH,
                "remaining_section_ids": [s["id"] for s in sections if not s["inspected"]],
                "current_candidate": copy.deepcopy(current),
                "last_valid_candidate": copy.deepcopy(self.state["last_valid_candidate"]),
                "validation": copy.deepcopy(self.state["validation"]),
                "rendered_views": list(self.state["rendered_views"]),
                "open_guesses": copy.deepcopy(self.open_guesses),
                "resolved_guesses": copy.deepcopy(self.state.get("resolved_guesses", [])),
                "model_choice_section_ids": sorted(self.state.get("model_choices", {})),
                "sheet_setup_ids": sorted(self.state.get("sheet_setups", {})),
                "sheet_setups": copy.deepcopy(list(self.state.get("sheet_setups", {}).values())),
                "description_phase": self.state.get("description_phase", "survey"),
                "description_next_view": copy.deepcopy(self.state.get("description_next_view")),
                "sheet_survey": copy.deepcopy(self.state.get("sheet_survey")),
                "described_views": copy.deepcopy(self.state.get("described_views", [])),
                "vessel_description": copy.deepcopy(self.state.get("vessel_description")),
                "phase1_only": self.state.get("phase1_only", False),
                # A repeat reading of a sheet-only first hull is open (first_hull_tools.begin_reading).
                "repeat_reading": self.state.get("reading_open") is not None,
                "view_count": len(self.state.get("views", [])),
                "non_improving_edits": self.state.get("non_improving_edits", 0),
                "best_valid_candidate": copy.deepcopy(self.state.get("best_valid_candidate")),
                "input_errors": self.state["input_errors"][:32],
                "sheet_only": self.state.get("sheet_only", False),
                "materialization": copy.deepcopy(self.state.get("materialization")), **SEMANTIC_FLAGS}

    def catalog(self) -> list[dict]:
        return [
            _definition("inspect_source", "Inspect up to 12 frozen drawing regions per call, returning source-supported hypotheses and preserved alternatives. Without section_ids, inspect the next uninspected batch. Candidate identity remains unapproved.",
                        {"section_ids": {"type": "array", "items": {"type": "string", "maxLength": 256},
                                         "minItems": 1, "maxItems": 300, "uniqueItems": True}}),
            _definition("select_contours", "Select already inspected source-bound candidate IDs. This creates a reversible provisional revision; it does not establish contour identity or approve geometry.",
                        {"selections": {"type": "array", "minItems": 1, "maxItems": 300,
                            "items": {"type": "object", "properties": {
                                "section_id": {"type": "string", "maxLength": 256},
                                "candidate_id": {"type": "string", "maxLength": 64}},
                                "required": ["section_id", "candidate_id"], "additionalProperties": False}}},
                        ["selections"]),
            _definition("build_provisional", "Run the unchanged, fail-closed drawing/CAD engine in an isolated worker using the current explicit candidate selections. Keep the last valid candidate if this attempt fails."),
            _definition("build_draft", "Build a best-effort draft after full inspection: take the best-scoring line where a section is ambiguous and span unreadable stations. Each such choice is recorded as an open guess. A draft is never verified and cannot be finished for review until a person resolves every guess."),
            _definition("propose_section", PROPOSE_SECTION_DESCRIPTION, PROPOSE_SECTION_PROPERTIES,
                        ["section_id", "form", "basis"]),
            _definition("render_candidate", "Reimport a verified exported STEP file and render a named physical view. Output identifies the revision and whether it is an older preserved candidate.",
                        {"view": {"type": "string", "enum": list(VIEWS)}}, ["view"]),
            _definition("validate_candidate", "Verify the current immutable run and independently reimport STEP. Report source-to-CAD section checks and remaining semantic review obligations; never grant engineering approval."),
        ]

    def _arguments(self, name, arguments):
        if not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False)) > 65536:
            raise ToolInputError("Tool arguments must be a bounded JSON object.")
        expected = {"inspect_source": {"section_ids"}, "select_contours": {"selections"},
                    "build_provisional": set(), "build_draft": set(), "build_first_hull": set(), "render_candidate": {"view"},
                    "validate_candidate": set(), "propose_section": PROPOSE_SECTION_ARGUMENTS,
                    **INVESTIGATION_ARGUMENTS}
        if name not in expected:
            raise ToolInputError("Unknown domain operation.")
        if name == "describe_vessel":
            extra = {k: arguments.pop(k) for k in list(arguments) if k != "description"}
            if extra:
                description = arguments.get("description")
                description = copy.deepcopy(description) if isinstance(description, dict) else {"original_description": description}
                description["outer_metadata"] = {"original": description.get("outer_metadata"), **extra}
                arguments["description"] = description
            arguments.setdefault("description", {})
        if set(arguments) - expected[name]:
            raise ToolInputError("Unsupported tool argument; paths and code are not accepted.")
        if name in INVESTIGATION_ARGUMENTS:
            try:
                check_investigation_arguments(name, arguments, self.spec)
            except ToolArgumentError as exc:
                raise ToolInputError(str(exc)) from None
        if name == "propose_section":
            known = {s.get("id") for s in self.spec.get("sections", []) if isinstance(s, dict)}
            if arguments.get("section_id") not in known:
                raise ToolInputError("section_id must be a known section of this task.")
            try:
                section_authoring.check_proposal_arguments(
                    {k: v for k, v in arguments.items() if v is not None})
            except section_authoring.ProposalError as exc:
                raise ToolInputError(str(exc)) from None
        if name == "inspect_source" and "section_ids" in arguments:
            ids = arguments["section_ids"]
            known = {s.get("id") for s in self.spec.get("sections", []) if isinstance(s, dict)}
            if not isinstance(ids, list) or not 1 <= len(ids) <= 300 or any(
                    not isinstance(s, str) or s not in known for s in ids) or len(set(ids)) != len(ids):
                raise ToolInputError("Section IDs must be unique known IDs from this task.")
        if name == "render_candidate" and arguments.get("view") not in VIEWS:
            raise ToolInputError("Choose body, plan, profile, or oblique.")
        if name == "select_contours":
            selections = arguments.get("selections")
            if not isinstance(selections, list) or not 1 <= len(selections) <= 300:
                raise ToolInputError("Supply 1..300 inspected candidate selections.")
            seen = set()
            for selection in selections:
                if not isinstance(selection, dict) or set(selection) != {"section_id", "candidate_id"}:
                    raise ToolInputError("Each selection must contain only section_id and candidate_id.")
                sid, cid = selection["section_id"], selection["candidate_id"]
                if not isinstance(sid, str) or not isinstance(cid, str) or sid in seen:
                    raise ToolInputError("Selection IDs must be strings and section IDs must be unique.")
                seen.add(sid)
                candidates = self.state["catalog"].get(sid, {}).get("candidates", [])
                if not any(c["candidate_id"] == cid and c["selectable"] for c in candidates):
                    raise ToolInputError("Candidate is unknown, belongs to another source, or lacks complete source support.")

    def execute(self, tool_name: str, arguments: dict) -> dict:
        try:
            with (self.root / "lock").open("a") as lock:
                try:
                    try_lock_exclusive(lock)
                except BlockingIOError as exc:
                    raise ToolInputError("Another domain action is already running.") from exc
                self.state = load_bounded_json(self.state_path, max_bytes=MAX_INSPECTION_BYTES,
                                               max_nodes=600_000)
                self._verify_inputs()
                state_before = self.state_path.read_bytes()
                try:
                    return self._execute_verified(tool_name, arguments)
                except (ToolInputError, ValueError, OSError, TypeError, KeyError, RuntimeError):
                    raise
                except Exception as exc:  # noqa: BLE001 - a tool bug must not end the run
                    return self._tool_failed(exc, state_before)
        except ToolInputError as exc:
            result = self._observation(False, "rejected", error_code="invalid_tool_arguments", message=str(exc))
            if tool_name == "assign_station":
                from .accuracy_feedback import candidate_catalog
                sid = arguments.get("section_id")
                section = next((s for s in self.spec["sections"] if s["id"] == sid), None)
                if section:
                    result["current_candidate_catalog"] = candidate_catalog(section, self.state["catalog"].get(sid, {}))
            return result
        except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
            return self._observation(False, "blocked", error_code="domain_integrity_or_input_error",
                                     exception_type=type(exc).__name__)

    def _tool_failed(self, exc: Exception, state_before: bytes) -> dict:
        """An unexpected error inside a verified tool call: undo its domain changes and say so.

        The run goes on: the controller receives an ordinary refusal, and the
        draft built before this call stays the best draft.
        """
        self.state_path.write_bytes(state_before)
        self.state = load_bounded_json(self.state_path, max_bytes=MAX_INSPECTION_BYTES, max_nodes=600_000)
        return self._observation(False, "tool_failed", error_code="tool_internal_error",
                                 exception_type=type(exc).__name__,
                                 message="The tool failed on this request and the domain is unchanged. "
                                         "Try a different action, or build_draft / finish with the best draft.")

    def _execute_verified(self, tool_name: str, arguments: dict) -> dict:
        """Run one tool on a verified domain (the caller holds the domain lock)."""
        # Only the Rust controller sets this flag, when a person keeps a
        # not-kept revision edit anyway; the model's tool schema has no such field.
        force_keep = (tool_name == "propose_section" and isinstance(arguments, dict)
                      and arguments.pop("operator_force_keep", False) is True)
        # Only the Rust controller sets this flag, on an edit a person asked
        # for (mark and revise): the edit must not worsen its section's ink fit.
        revision_target = (tool_name == "propose_section" and isinstance(arguments, dict)
                           and arguments.pop("revision_target", False) is True)
        self._arguments(tool_name, arguments)
        if self.cancel_event is not None and self.cancel_event.is_set():
            return self._observation(False, "cancelled", error_code="cancelled")
        method = getattr(self, "_" + tool_name)
        judged = tool_name in ("propose_section", "assign_station") and self.state.get("vessel_table")
        incumbent = copy.deepcopy(self.state) if judged and not force_keep else None
        fit_before = self.state.get("fit_score", {}).get("combined_fit")
        result = method(**arguments)
        if force_keep and judged and result.get("ok"):
            from .fit_feedback import score, current_table
            after = score(self)
            self.state["vessel_table"] = current_table(self).to_json()
            self.state["fit_score"] = after
            self._save()
            result["fit_comparison"] = {"keep": True, "operator_forced": True, "fit_before": fit_before,
                                        "fit_after": after.get("combined_fit"),
                                        "reason": "A person kept this edit although the keep rule did not."}
        if incumbent is not None and result.get("ok"):
            from .fit_feedback import score, current_table
            from .whole_vessel_score import keep_edit
            before = incumbent.get("fit_score", {})
            after = score(self)
            sid = arguments.get("section_id")
            old_curve = next((r["points_yz_m"] for r in incumbent["vessel_table"]["stations"] if r["id"] == sid), None)
            new_curve = self._section_curve(sid)
            identical = old_curve == new_curve
            # A station with no measurable ink has no entry, or a null one.
            old_ink = (before.get("station_ink_fit") or {}).get(sid) or {}
            new_ink = (after.get("station_ink_fit") or {}).get(sid) or {}
            protected_ink = old_ink.get("near_fraction", 0) >= .9 and old_ink.get("rms_m") is not None
            fit_key, draft_after = "combined_fit", None
            draft_before = incumbent.get("draft_fit") or {}
            if EDIT_KEEP_FIT == "draft_fit" and draft_before.get("draft_fit") is not None:
                from .draft_fit import task_score
                draft_after = task_score(self, current_table(self))
                if draft_after.get("draft_fit") is not None:
                    fit_key = "draft_fit"
            decision = keep_edit({**before, "draft_fit": draft_before.get("draft_fit")},
                                 {**after, "draft_fit": (draft_after or {}).get("draft_fit")},
                                 before.get("cells"), after.get("cells"), gap_fill_only=old_curve is None,
                                 fit_key=fit_key)
            if protected_ink and new_ink.get("rms_m", float("inf")) > old_ink["rms_m"] + 1e-6:
                decision = {**decision, "keep": False, "reason": "Kept supported ink; proposed curve has worse ink RMS.",
                            "ink_rms_before_m": old_ink["rms_m"], "ink_rms_after_m": new_ink.get("rms_m")}
            elif revision_target and revision_ink_worse(old_ink, new_ink):
                decision = {**decision, "keep": False,
                            "reason": (f"A revision must not worsen its section's ink fit: ink RMS "
                                       f"{old_ink['rms_m']:.2f} m before, {new_ink.get('rms_m', float('nan')):.2f} m "
                                       "after. Follow the drawn ink of this section more closely."),
                            "ink_rms_before_m": old_ink["rms_m"], "ink_rms_after_m": new_ink.get("rms_m")}
            if identical or not decision["keep"]:
                self.state = incumbent
                self.state["non_improving_edits"] = self.state.get("non_improving_edits", 0) + 1
                self._save()
                result = self._observation(True, "kept_previous_curve", fit_comparison=decision,
                    repeated_proposal=identical,
                    message=f"Kept previous curve: {fit_key.replace('_', ' ')} {decision.get('fit_before')} vs proposed {decision.get('fit_after')}. Finish the best draft or try a different section.")
            else:
                self.state["vessel_table"] = current_table(self).to_json()
                self.state["fit_score"] = after
                if draft_after is not None:
                    self.state["draft_fit"] = draft_after
                self.state["non_improving_edits"] = 0
                self._save()
                result["fit_comparison"] = decision
        if tool_name in ("assign_station", "enumerate_strokes", "inspect_source", "trace_from_point", "trace_corridor"):
            from .accuracy_feedback import candidate_catalog, candidate_feedback
            by_id = {s["id"]: s for s in self.spec.get("sections", [])}
            sid = arguments.get("section_id")
            ids = [sid] if sid in by_id else result.get("returned_section_ids", [])
            result["candidate_guidance"] = [{"section_id": section_id,
                "candidates": candidate_catalog(by_id[section_id], self.state["catalog"].get(section_id, {}))}
                for section_id in ids[:12] if section_id in by_id]
            if tool_name == "assign_station" and sid in by_id:
                candidate = next((c for c in self.state["catalog"].get(sid, {}).get("candidates", [])
                    if c["candidate_id"] == arguments.get("candidate_id")), {})
                result["accuracy_feedback"] = candidate_feedback(by_id[sid], candidate, arguments.get("label_text", ""))
        if tool_name == "build_draft":
            from .accuracy_feedback import candidate_feedback
            chosen = {g["section_id"]: g["chosen_candidate_id"] for g in self.open_guesses}
            chosen.update(self.state["selected"])
            result["section_accuracy_feedback"] = [{"section_id": s["id"],
                **candidate_feedback(s, next((c for c in self.state["catalog"].get(s["id"], {}).get("candidates", [])
                    if c["candidate_id"] == chosen.get(s["id"])), {}))}
                for s in self.spec["sections"] if chosen.get(s["id"])]
        return result

    def _observation(self, ok, status, **values):
        try:
            revision = self.revision_id
        except (ValueError, TypeError, KeyError):
            revision = None
        return {"ok": ok, "status": status, "revision_id": revision,
                "generation_id": self.generation_id if revision is not None else None,
                "selected_count": len(self.state["selected"]),
                "remaining_count": len(self.spec.get("sections", [])) - len(self.state["selected"]),
                **SEMANTIC_FLAGS, **values}

    def _worker(self, operation, request, out, *, native=False):
        out.parent.mkdir(parents=True, exist_ok=True)
        request_path = self.root / f"request-{uuid4().hex}.json"
        write_json(request_path, request)
        limits = replace(DEFAULT_LIMITS, wall_seconds=120 if native else 60,
                         cpu_seconds=90 if native else INSPECTION_CPU_SECONDS, output_bytes=64 * 1024**2)
        command = [sys.executable, "-m", "vessel_reconstruction.agent_render_worker",
                   "--operation", operation, "--request", str(request_path), "--out", str(out),
                   "--limits", json.dumps(asdict(limits)), "--parent", str(os.getpid())]
        try:
            outcome = supervise_process(command, limits=limits, cancel_event=self.cancel_event, output_dir=out)
            result = None
            if outcome["state"] == "exited" and outcome["exit_code"] == 0:
                result = load_bounded_json(out / "observation.json", max_bytes=MAX_INSPECTION_BYTES,
                                            max_nodes=600_000)
            elif outcome["state"] == "exited":
                outcome["state"] = "failed"
                error_path = out / "worker-error.json"
                if error_path.is_file():
                    outcome["worker_error"] = load_bounded_json(error_path, max_bytes=4096)
            return outcome, result
        finally:
            request_path.unlink(missing_ok=True)

    def _inspection_batch(self, requested: list[str]) -> list[str]:
        """The first requested sections whose estimated inspection CPU fits the budget.

        Not-yet-inspected sections are costed by their ROI pixel count; cached
        ones cost nothing. The first section is always taken, so a batch is
        never empty; at most INSPECTION_BATCH sections are taken.
        """
        budget = INSPECTION_BUDGET_SHARE * INSPECTION_CPU_SECONDS
        by_id = {s["id"]: s for s in self.spec["sections"]}
        batch, estimate = [], 0.0
        for sid in requested[:INSPECTION_BATCH]:
            cost = 0.0 if sid in self.state["catalog"] else estimated_inspection_cpu_seconds(by_id[sid])
            if batch and estimate + cost > budget:
                break
            batch.append(sid)
            estimate += cost
        return batch

    def _inspect_source(self, section_ids=None):
        if self.state["input_errors"]:
            return self._observation(False, "blocked", validation_errors=self.state["input_errors"][:32])
        if self.spec.get("input_mode", "calibrated_section_curves") != "calibrated_section_curves":
            return self._observation(False, "blocked", error_code="unsupported_agent_input_mode",
                                     message="Contour tools require calibrated section drawings; the table engine remains available separately.")
        requested = section_ids or [s["id"] for s in self.spec["sections"] if s["id"] not in self.state["catalog"]]
        if not requested:
            requested = [s["id"] for s in self.spec["sections"]]
        ids = self._inspection_batch(requested)
        missing = [sid for sid in ids if sid not in self.state["catalog"]]
        resources = {}
        if missing:
            out = self.root / "inspections" / uuid4().hex
            outcome, result = self._worker("inspect", {"spec_path": str(self.spec_path),
                                                        "section_ids": missing}, out)
            resources = {"worker_state": outcome["state"], "wall_seconds": outcome["elapsed_seconds"]}
            if result is None:
                limited = outcome.get("worker_error", {}).get("error_code") == "resource_limit"
                if limited:
                    by_id = {section["id"]: section for section in self.spec["sections"]}
                    for sid in missing:
                        section = by_id[sid]
                        self.state["catalog"].setdefault(sid, {
                            "section_id": sid, "source_sha256": self.state["sources"]["source"]["sha256"],
                            "x_m": section["x_m"], "roi_px": section["roi_px"],
                            "calibration": section["calibration"], "candidates": [],
                            "inspection_failure": "resource_limit",
                            "grid_evidence": {"lattice_detected": False, "unique_non_grid_candidate_id": None,
                                              "non_grid_competing_components": None}, **SEMANTIC_FLAGS})
                    self._save()
                return self._observation(False, outcome["state"],
                    error_code="resource_limit" if limited else "inspection_worker_failed",
                    message="Source inspection exceeds the bounded evidence budget." if limited
                            else "Source inspection worker failed; no recoverable diagnostic is available.",
                    failed_section_ids=missing, recovery_tools=["enumerate_strokes", "trace_from_point", "trace_corridor"] if limited else [],
                    resources=resources)
            for section in result["sections"]:
                # Coordinates/complete diagnostics remain in immutable inspection
                # evidence files; persistent selection state only needs corridors.
                section.pop("retained_diagnostics", None)
                for candidate in section["candidates"]:
                    candidate.pop("source_points_px", None)
                self.state["catalog"][section["section_id"]] = section
            artifacts = [_artifact(out / a["file"], self.task_dir, kind=a["kind"],
                                   **{k: v for k, v in a.items() if k not in {"file", "kind"}})
                         for a in result["artifacts"]]
            self.state["inspection_artifacts"].extend(artifacts)
            self._save()
        sections = []
        for sid in ids:
            item = copy.deepcopy(self.state["catalog"][sid])
            for candidate in item["candidates"]:
                candidate.pop("contour_selection", None)
                candidate.pop("source_points_px", None)
                if "authored" in candidate:  # The curve stays in the task state.
                    candidate["authored"] = {k: candidate["authored"][k] for k in ("source_label", "basis")}
            # Full diagnostics and coordinates remain in source-bound artifacts.
            item.pop("retained_diagnostics", None)
            sections.append(item)
        page_artifacts = [a for a in self.state["inspection_artifacts"] if
                          a["kind"] == "source_page" or a.get("evidence_kind") == "source_page"][-2:]
        failed_ids = [item["section_id"] for item in sections if item.get("inspection_failure")]
        observation = self._observation(not failed_ids, "resource_limited" if failed_ids else "observed",
            error_code="resource_limit" if failed_ids else None,
            message="Cached failed inspection; use bounded ink tools." if failed_ids else "Source inspection evidence.",
            failed_section_ids=failed_ids, sections=sections, resources=resources,
            returned_section_ids=list(ids), remaining_requested_section_ids=requested[len(ids):],
            remaining_section_ids=[s["id"] for s in self.spec["sections"] if s["id"] not in self.state["catalog"]][:24],
            artifacts=[a for a in self.state["inspection_artifacts"] if a.get("section_id") in ids] + page_artifacts)
        # Native evidence remains complete; the model observation is bounded.
        # Explicitly report omitted sections, so they can be inspected again.
        while len(json.dumps(observation).encode()) > 48 * 1024 and len(observation["sections"]) > 1:
            omitted = observation["sections"].pop()["section_id"]
            observation["returned_section_ids"].remove(omitted)
            observation["remaining_requested_section_ids"].insert(0, omitted)
            observation["artifacts"] = [a for a in observation["artifacts"] if a.get("section_id") != omitted]
        return observation

    def _select_contours(self, selections):
        selected = dict(self.state["selected"])
        for item in selections:
            selected[item["section_id"]] = item["candidate_id"]
        # Selecting a guessed section resolves its guess: the same candidate
        # confirms it, another candidate replaces it. The Rust controller lets
        # only an operator select a guessed section.
        chosen = {item["section_id"]: item["candidate_id"] for item in selections}
        resolved = [g for g in self.open_guesses if g["section_id"] in chosen]
        changed = selected != self.state["selected"] or bool(resolved)
        if changed:
            if resolved:
                history = self.state.setdefault("resolved_guesses", [])
                for guess in resolved:
                    candidate = chosen[guess["section_id"]]
                    history.append({**guess, "status": "resolved", "resolved_candidate_id": candidate,
                                    "resolution": ("confirmed" if candidate == guess["chosen_candidate_id"]
                                                   else "replaced")})
                self.state["guesses"] = [g for g in self.open_guesses if g["section_id"] not in chosen]
            self.state.update(selected=selected, revision=self.state["revision"] + 1,
                              validation=None, rendered_views=[])
            self._write_revision()
            self._save()
        return self._observation(True, "provisional_selection", changed=changed,
                                 selection_actor="agent_or_explicit_harness_policy",
                                 selected=[{"section_id": sid, "candidate_id": cid} for sid, cid in sorted(selected.items())],
                                 alternatives_retained=True,
                                 message="Source-pixel corridors constrain measurement; contour identity still requires human review.")

    def _write_revision(self):
        directory = self.root / "revisions" / self.revision_id
        directory.mkdir(parents=True, exist_ok=True)
        spec = copy.deepcopy(self.spec)
        spec.pop("draft", None)  # Only the open guesses below make a revision a draft.
        for role in self.state["sources"]:
            spec[role]["file"] = os.path.relpath(self.root / "input" / self.state["sources"][role]["file"], directory)
        guesses = {g["section_id"]: g for g in self.open_guesses}
        kept = []
        for section in spec["sections"]:
            guess = guesses.get(section["id"])
            cid = self.state["selected"].get(section["id"])
            if guess is not None:
                cid = guess["chosen_candidate_id"]
                if cid is None:
                    continue  # Unreadable station: the draft loft spans it.
            kept.append(section)
            if cid is None:
                continue
            candidate = next(c for c in self.state["catalog"][section["id"]]["candidates"] if c["candidate_id"] == cid)
            if "authored" in candidate:
                # The model wrote this section; the build uses its curve as is.
                authored = candidate["authored"]
                section.pop("contour_selection", None)
                section["authored"] = {key: copy.deepcopy(authored[key])
                                       for key in ("source_label", "basis", "points_yz_m")}
                section["evidence"] = (section.get("evidence", "")[:7000] + " Model-authored section " + cid + " (" +
                                       authored["source_label"] + "); not verified; a person must confirm or replace it.")
                continue
            if not candidate.get("declared_pieces"):
                section["contour_selection"] = copy.deepcopy(candidate["contour_selection"])
            if candidate.get("z_range_m") is not None:
                # A corridor trace that ends inside the calibrated range is
                # read only where its ink is (investigation.corridor_trace).
                section["z_min_m"], section["z_max_m"] = candidate["z_range_m"]
            prior = section.get("evidence", "Caller-supplied calibration.")
            if guess is not None:
                section["evidence"] = (prior[:7000] + " Draft guess " + guess["guess_id"] + " took " + cid +
                                        "; not verified; a person must confirm or replace it.")
            else:
                section["evidence"] = (prior[:7000] + " Provisional source-bound agent/policy selection " + cid +
                                        "; excluded strokes retained; human semantic review required.")
        spec["sections"] = kept
        if self.state.get("first_hull_spec"):
            present = {s["id"] for s in kept}
            spec["sections"].extend(copy.deepcopy(s) for s in self.state["first_hull_spec"]["sections"] if s["id"] not in present)
        if self.state.get("first_hull_spec"):
            fitted = {s["id"]: s for s in self.state["first_hull_spec"]["sections"]}
            for index, section in enumerate(spec["sections"]):
                sid = section["id"]
                if sid not in self.state.get("authored_sections", {}) and sid not in self.state.get("model_choices", {}):
                    spec["sections"][index] = copy.deepcopy(fitted.get(sid, section))
        selection = {"revision_id": self.revision_id, "generation_id": self.generation_id,
                     "selected": self.state["selected"], "source_sha256": self.state["sources"], **SEMANTIC_FLAGS}
        if self.open_guesses:
            spec["draft"] = {"status": DRAFT_STATUS, "guesses": copy.deepcopy(self.open_guesses)}
            selection["guesses"] = copy.deepcopy(self.open_guesses)
        write_json(directory / "spec.json", spec)
        write_json(directory / "selection.json", selection)
        return directory / "spec.json"

    def _build_provisional(self):
        previous = next((b for b in reversed(self.state["builds"]) if b["generation_id"] == self.generation_id
                         and b["revision_id"] == self.revision_id), None)
        if previous:
            return self._observation(previous["valid"], previous["status"], candidate=previous,
                                     reused=True, changed=False, validation_errors=previous.get("gaps", []))
        spec = self._write_revision()
        out = self.root / "builds" / f"{self.revision_id}-{uuid4().hex[:12]}"
        outcome = run_isolated(spec, out, export_cad=True, cancel_event=self.cancel_event)
        result = outcome.get("result")
        valid = bool(result and result.get("status") == "review_required" and result.get("exports", {}).get("step"))
        candidate = {"id": self.generation_id, "generation_id": self.generation_id,
                     "revision_id": self.revision_id, "path": out.relative_to(self.task_dir).as_posix(),
                     "status": "review_required" if valid else outcome["state"], "valid": valid,
                     # A draft build carries open guesses; it is never validated.
                     "draft": bool(self.open_guesses),
                     "run_id": result.get("run_id") if result else None,
                     "gaps": result.get("gaps", [])[:64] if result else [{"kind": outcome.get("error_code", outcome["state"])}],
                     "metrics": result.get("metrics", {}) if result else {}, **SEMANTIC_FLAGS}
        self.state["builds"].append(candidate)
        if valid and not self.state.get("vessel_table"):
            self.state["last_valid_candidate"] = candidate
        if valid and self.state.get("vessel_table"):
            candidate["combined_fit"] = self.state.get("fit_score", {}).get("combined_fit")
            candidate["draft_fit"] = (self.state.get("draft_fit") or {}).get("draft_fit")
            best = self.state.get("best_valid_candidate")
            # The same fit as the keep rule (EDIT_KEEP_FIT) ranks the builds.
            key = ("draft_fit" if EDIT_KEEP_FIT == "draft_fit" and candidate["draft_fit"] is not None
                   and (best or {}).get("draft_fit") is not None else "combined_fit")
            fit = candidate[key]
            if best is None or fit is None or best.get(key) is None or fit >= best[key]:
                self.state["best_valid_candidate"] = copy.deepcopy(candidate)
            self.state["last_valid_candidate"] = copy.deepcopy(self.state.get("best_valid_candidate") or candidate)
        self.state.update(validation=None, rendered_views=[])
        self._save()
        artifacts = []
        if result:
            artifacts.append(_artifact(out / "result.json", self.task_dir, kind="immutable_engine_record"))
            if valid:
                artifacts.extend(_artifact(out / result["exports"][key], self.task_dir, kind="provisional_" + key)
                                 for key in ("step", "stl", "mesh") if key in result["exports"])
        return self._observation(valid, candidate["status"], candidate=candidate,
                                 next_actions=[{"section_id": item.get("section_id"), "gap": item.get("kind"),
                                                "suggestion": "Re-trace this section, pick another candidate, or finish to accept draft."}
                                               for item in candidate["gaps"]],
                                 validation_errors=candidate["gaps"], artifacts=artifacts,
                                 resources=outcome.get("resources", {}), changed=True,
                                 last_valid_preserved=self.state["last_valid_candidate"] is not None)

    def _build_first_hull(self):
        from .first_hull_tools import build_first_hull, start_next_reading
        observation = build_first_hull(self)
        if observation.get("ok"):
            next_reading = start_next_reading(self)
            if next_reading:
                observation["next_reading"] = next_reading
                observation["message"] = (observation.get("message", "") + " " + next_reading["message"])[:600]
        return observation

    def _build_draft(self):
        """Best-effort build: guess where the source is ambiguous, then build.

        The new guesses replace older open guesses (a person can resolve some in
        between). Without an unselected section this is an ordinary build with
        no guess.
        """
        sections = [s for s in self.spec.get("sections", []) if isinstance(s, dict)]
        if not sections or any(s["id"] not in self.state["catalog"] for s in sections):
            return self._observation(False, "blocked", error_code="draft_requires_complete_inspection",
                                     message="Inspect every section before a draft is built.")
        self._assign_shared_panels()
        guesses = make_guesses(sections, self.state["selected"], self.state["catalog"],
                               self.state.get("model_choices"), self.state.get("authored_sections"))
        if guesses != self.open_guesses:
            self.state.update(guesses=guesses, revision=self.state["revision"] + 1,
                              validation=None, rendered_views=[])
            self._save()
        observation = self._build_provisional()
        observation["draft"] = ({"status": DRAFT_STATUS, "guesses": copy.deepcopy(guesses)}
                                if guesses else None)
        record = self._build_record(observation.get("candidate"))
        if record is not None and record.get("sections"):
            observation["section_sources"] = section_sources(record["sections"], guesses)
        return observation

    def _build_record(self, candidate):
        """The immutable result record of a build, or None."""
        if not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str):
            return None
        try:
            path = safe_relative_file(self.task_dir, candidate["path"] + "/result.json")
        except (ValueError, OSError):
            return None
        return load_bounded_json(path, max_bytes=MAX_INSPECTION_BYTES, max_nodes=600_000)

    # ------------------------------------------------------------ authoring
    def _section_curve(self, section_id):
        """The curve (points_yz_m) a draft would build for a section, or None.

        A model-authored candidate gives its curve; a traced candidate (the
        selection, the model's station claim or the best guess) is converted
        from its source pixels with the section calibration.
        """
        from . import investigation as inv
        from .draft import candidate_score
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        candidates = [c for c in self.state["catalog"].get(section_id, {}).get("candidates", [])
                      if c.get("selectable") is True]
        choices = (self.state["selected"],
                   {k: v["candidate_id"] for k, v in self.state.get("authored_sections", {}).items()},
                   {k: v["candidate_id"] for k, v in self.state.get("model_choices", {}).items()})
        chosen = None
        for choice in choices:
            if section_id in choice:
                chosen = next((c for c in candidates if c["candidate_id"] == choice[section_id]), None)
                if chosen is not None:
                    break
        if chosen is None:
            traced = [c for c in candidates if not c.get("model_traced")]
            chosen = max(traced, key=candidate_score, default=None)
        if chosen is None:
            return None
        if "authored" in chosen:
            return chosen["authored"]["points_yz_m"]
        trace = inv.dense_trace(chosen)
        if trace is None or len(trace[0]) < 5:
            return None
        calibration = section["calibration"]
        ppm = float(calibration["pixels_per_metre"])
        heights = (float(calibration["baseline_px"]) - trace[0]) / ppm
        breadths = np.maximum(0.0, (trace[1] - float(calibration["centerline_px"])) / ppm)
        order = np.argsort(heights)
        return [[float(breadths[i]), float(heights[i])] for i in order]

    def _neighbour_curves(self, section_id):
        """The nearest sections below and above in x that have a curve, as (x_m, points)."""
        x = next(s["x_m"] for s in self.spec["sections"] if s["id"] == section_id)
        found = {"lower": None, "upper": None}
        others = sorted((s for s in self.spec["sections"] if s["id"] != section_id),
                        key=lambda s: abs(s["x_m"] - x))
        for other in others:
            side = "lower" if other["x_m"] < x else "upper"
            if found[side] is None:
                curve = self._section_curve(other["id"])
                if curve is not None:
                    found[side] = (other["x_m"], curve)
            if all(found.values()):
                break
        return found["lower"], found["upper"]

    def _propose_section(self, section_id, form, basis, replaces="none", **parameters):
        """Make the model's section shape a fair curve and this section's draft choice."""
        section = next(s for s in self.spec["sections"] if s["id"] == section_id)
        entry = self.state["catalog"].get(section_id)
        candidates = entry["candidates"] if entry else []
        if replaces != "none" and not any(c["candidate_id"] == replaces for c in candidates):
            return self._observation(False, "proposal_refused", error_code="unknown_replaced_candidate",
                                     message="replaces must be 'none' or a candidate id of this section.")
        lower, upper = self._neighbour_curves(section_id)
        constraints = self.spec.get("constraints") or {}
        arguments = {"form": form, "basis": basis, "replaces": replaces,
                     **{k: v for k, v in parameters.items() if v is not None}}
        try:
            authored = section_authoring.author_section(
                arguments, x_m=section["x_m"], z_limits=(section["z_min_m"], section["z_max_m"]),
                half_beam_limit=constraints["beam_m"] / 2 if "beam_m" in constraints else None,
                depth_limit=constraints.get("depth_m"), lower=lower, upper=upper)
        except section_authoring.ProposalError as exc:
            return self._observation(False, "proposal_refused", error_code="unusable_section_proposal",
                                     message=str(exc), section_id=section_id)
        warnings = authored["warnings"]
        selected = self.state["selected"].get(section_id)
        label = "ai_corrected" if replaces != "none" else "ai_inferred"
        previous = self.state.get("authored_sections", {}).get(section_id)
        if replaces == "none" and selected is not None:
            label = "ai_corrected"
            warnings.append(f"Replaces the selected trace {selected}; labelled ai_corrected.")
        elif replaces == "none" and previous and previous["verifier_evidence"]["source_label"] == "ai_corrected":
            label = "ai_corrected"  # A revision of a correction still replaces that trace.
        cid = "authored-" + digest_object({"section": section_id, "arguments": arguments,
                                           "points": authored["points_yz_m"]})[:20]
        parameters = {k: v for k, v in arguments.items() if k not in ("form", "basis", "replaces")}
        candidate = {"candidate_id": cid, "hypothesis": "model_authored_" + form, "generated_by": ["propose_section"],
                     "selectable": True, "model_traced": True, "grid_supported_hypothesis": False,
                     "non_grid_competing_components": None, "identity_certified": False,
                     "authored": {"source_label": label, "basis": basis, "form": form, "replaces": replaces,
                                  "parameters": parameters, "points_yz_m": authored["points_yz_m"],
                                  "checks": authored["checks"], "warnings": warnings}}
        if entry is None:
            # A section that was never inspected still gets a catalog entry, so
            # the draft can be built; its only line is the model's.
            entry = self.state["catalog"].setdefault(section_id, {
                "section_id": section_id, "source_sha256": self.state["sources"]["source"]["sha256"],
                "x_m": section["x_m"], "roi_px": section["roi_px"], "calibration": section["calibration"],
                "candidates": [], "inspection_failure": None,
                "grid_evidence": {"lattice_detected": False, "unique_non_grid_candidate_id": None,
                                  "non_grid_competing_components": None}, **SEMANTIC_FLAGS})
        # Only the newest proposal of a section stays in the catalog; older
        # ones stay in their evidence files.
        entry["candidates"] = [c for c in entry["candidates"] if "authored" not in c] + [candidate]
        evidence = {"verifier": "section_authoring_checks_v1", "passed": True, "identity_certified": False,
                    "source_label": label, "form": form, "checks": authored["checks"], "warnings": warnings[:8]}
        record = {"candidate_id": cid, "verifier_evidence": evidence}
        self.state.setdefault("authored_sections", {})[section_id] = record
        self.state.setdefault("model_choices", {}).pop(section_id, None)
        self.state["selected"].pop(section_id, None)
        selectable = [c for c in entry["candidates"] if c.get("selectable") is True]
        guess = model_authored_guess(section, selectable, record)
        guesses = [g for g in self.open_guesses if g["section_id"] != section_id] + [guess]
        order = {s["id"]: i for i, s in enumerate(self.spec["sections"])}
        self.state.update(guesses=sorted(guesses, key=lambda g: order[g["section_id"]]),
                          revision=self.state["revision"] + 1, validation=None, rendered_views=[])
        directory = self.root / "authored"
        directory.mkdir(exist_ok=True)
        write_json(directory / f"{cid}.json", {"section_id": section_id, **candidate,
                                               "neighbours_x_m": [n[0] for n in (lower, upper) if n is not None]})
        view, artifact = self._authored_overlay(section, candidate, replaces)
        self._save()
        points = authored["points_yz_m"]
        summary = [points[i] for i in np.linspace(0, len(points) - 1, 7).astype(int)]
        return self._observation(True, "section_proposed", section_id=section_id, candidate_id=cid,
                                 source_label=label, warnings=warnings, checks=authored["checks"],
                                 curve_summary_yz_m=summary, guess=copy.deepcopy(guess), view=view,
                                 artifacts=[artifact],
                                 note=("Orange: your section on the source panel (blue: the trace it replaces). "
                                       "build_draft uses it, labelled " + label + "; propose again to revise it."))

    def _authored_overlay(self, section, candidate, replaces):
        """The proposed curve (orange) and any replaced trace (blue) on the source panel."""
        from . import investigation as inv
        image, _, source_sha = self._source()
        calibration = section["calibration"]
        ppm = float(calibration["pixels_per_metre"])
        centre, baseline = float(calibration["centerline_px"]), float(calibration["baseline_px"])
        pixels = [(centre + y * ppm, baseline - z * ppm) for y, z in candidate["authored"]["points_yz_m"]]
        replaced = next((c for c in self.state["catalog"][section["id"]]["candidates"]
                         if c["candidate_id"] == replaces), None)
        trace = inv.dense_trace(replaced) if replaced else None
        region = inv.clip_region(section["roi_px"], image.shape[1], image.shape[0])

        def overlay(draw, to_view):
            if trace is not None:
                draw.line([to_view(x, y) for x, y in zip(trace[1][::3], trace[0][::3])], fill=(40, 90, 220), width=2)
            draw.line([to_view(x, y) for x, y in pixels], fill=(245, 130, 48), width=3)

        payload, meta = inv.render_view(image, region, inv.MAX_VIEW_SIDE_PX, overlay=overlay)
        return self._store_view(payload, meta, "authored_section", source_sha, section_id=section["id"],
                                candidate_id=candidate["candidate_id"])

    def _verified_candidate(self, *, allow_previous=False, allow_draft=False):
        from .run_record import verify_run
        candidate = next((b for b in reversed(self.state["builds"]) if b["generation_id"] == self.generation_id
                          and b["revision_id"] == self.revision_id), None)
        if not candidate or candidate.get("valid") is not True:
            if allow_previous:
                candidate = self.state["last_valid_candidate"]
            if not candidate or candidate.get("valid") is not True:
                raise ToolInputError("No valid provisional STEP exists for this revision; build or revise the source selections.")
        if candidate.get("draft") is True and not allow_draft:
            raise ToolInputError("A draft is not verified and cannot be validated; a person must confirm or replace each guess first.")
        path = safe_relative_file(self.task_dir, candidate["path"] + "/result.json").parent
        verification = verify_run(path)
        if verification.get("valid") is not True:
            raise ToolInputError("Candidate evidence changed or failed immutable-run verification.")
        return candidate, path

    def _render_candidate(self, view):
        candidate, run = self._verified_candidate(allow_previous=True, allow_draft=True)
        out = self.root / "renders" / uuid4().hex
        request = {"run_dir": str(run), "view": view}
        overlay_request, overlay_warning = self._station_overlay_request(candidate)
        if overlay_request is not None:
            request["station_overlay"] = overlay_request
        outcome, result = self._worker("render", request, out, native=True)
        if result is None:
            return self._observation(False, outcome["state"], error_code="render_worker_failed")
        station_overlay, overlay_artifacts = self._station_overlay_result(result, out, overlay_warning)
        stale = candidate["generation_id"] != self.generation_id or candidate["revision_id"] != self.revision_id
        if not stale and view not in self.state["rendered_views"]:
            self.state["rendered_views"].append(view)
            self._save()
        return self._observation(True, "rendered", view=view, rendered_generation_id=candidate["generation_id"],
                                 rendered_revision_id=candidate["revision_id"], stale_candidate=stale,
                                 geometry_audit=result["geometry_audit"],
                                 artifacts=[_artifact(out / "render.png", self.task_dir, kind="step_reimport_render", view=view,
                                                      model_eligible=False),
                                            _artifact(out / result["model_observation"]["file"], self.task_dir,
                                                      kind="model_observation", view=view,
                                                      **{k: v for k, v in result["model_observation"].items() if k != "file"})]
                                 + overlay_artifacts,
                                 station_overlay=station_overlay,
                                 fit_score={k: v for k, v in self.state.get("fit_score", {}).items() if k != "cells"},
                                 resources={"wall_seconds": outcome["elapsed_seconds"]})

    def _station_overlay_request(self, candidate):
        """Render-worker inputs of the station overlay, as (request, None) or (None, warning).

        The source is saved once as PNG beside the domain, because the worker
        must not parse a PDF. A station that the build does not contain gets
        its best trace as the reference curve.
        """
        try:
            from PIL import Image
            image, _, source_sha = self._source()
            source_png = self.root / f"overlay-source-{source_sha[:24]}.png"
            if not source_png.is_file():
                partial = source_png.with_suffix(".partial.png")
                Image.fromarray(image).save(partial)
                partial.replace(source_png)
            record = self._build_record(candidate) or {}
            built = {s.get("id") for s in record.get("sections", [])}
            sections, references = [], {}
            for section in self.spec.get("sections", []):
                sections.append({key: section[key] for key in ("id", "x_m", "roi_px", "calibration")})
                if section["id"] not in built:
                    curve = self._section_curve(section["id"])
                    if curve is not None:
                        references[section["id"]] = curve
            return {"source_image": str(source_png), "sections": sections, "references": references}, None
        except Exception as exc:
            return None, "Station overlay skipped: " + type(exc).__name__ + "."

    def _station_overlay_result(self, result, out, warning):
        """The render observation's station_overlay field and its artifacts; never fails the render."""
        overlay = result.get("station_overlay")
        if not isinstance(overlay, dict) or overlay.get("status") != "rendered":
            reason = overlay.get("warning") if isinstance(overlay, dict) else None
            return {"status": "skipped", "warning": warning or reason or "Station overlay skipped."}, []
        try:
            artifacts = []
            for item in overlay["artifacts"]:
                kind, name = item["kind"], item["file"]
                if kind not in OVERLAY_ARTIFACT_KEYS or not OVERLAY_FILE_NAMES[kind].fullmatch(name):
                    raise ValueError("Unexpected overlay artifact.")
                # The worker output is untrusted: copy only the known display keys.
                extra = {k: item[k] for k in OVERLAY_ARTIFACT_KEYS[kind] if k in item}
                extra["model_eligible"] = False
                artifacts.append(_artifact(out / name, self.task_dir, kind=kind, **extra))
        except (ValueError, OSError, TypeError, KeyError) as exc:
            return {"status": "skipped", "warning": "Station overlay skipped: " + type(exc).__name__ + "."}, []
        return {key: value for key, value in overlay.items() if key != "artifacts"}, artifacts

    def _validation_context(self, candidate, run):
        from .validation_contract import build_context
        return build_context(self.task_dir, self.root, self.state, self.captured_spec, candidate, run)

    def validation_context(self):
        """Fresh identity/evidence context for an independent finalization gate.

        This operation never computes a new audit or clears a cached failure.
        It reloads the checkpoint and rechecks current bytes under the domain
        lock, so finalization cannot depend only on a tool response envelope.
        """
        with self.validation_guard() as context:
            return context

    @contextmanager
    def validation_guard(self):
        """Keep a current validation context stable through controller commit.

        The caller must retain this guard until its review-ready event has been
        committed. All allowed domain mutation operations acquire the same lock.
        A snapshot returned after releasing this guard is not an atomic finish.
        """
        with (self.root / "lock").open("a") as lock:
            try_lock_exclusive(lock)
            self.state = load_bounded_json(self.state_path, max_bytes=MAX_INSPECTION_BYTES,
                                           max_nodes=600_000)
            self._verify_inputs()
            candidate, run = self._verified_candidate()
            yield self._validation_context(candidate, run)

    def _validate_candidate(self):
        from .validation_contract import (ValidationContractError, make_contract,
                                           verify_validation)
        candidate, run = self._verified_candidate()
        context = self._validation_context(candidate, run)
        if self.state.get("validation") is not None:
            validation = self.state["validation"]
            try:
                assessment = verify_validation(validation, context, self.task_dir)
            except (ValidationContractError, ValueError, OSError, TypeError, KeyError) as exc:
                return self._observation(False, "validation_failed", error_code="validation_cache_invalid",
                                         exception_type=type(exc).__name__, reused=True,
                                         message="Cached audit is stale, malformed, incomplete or changed; original evidence is retained.")
            return self._observation(assessment.passed,
                                     "validated_review_required" if assessment.passed else "validation_failed",
                                     validation=validation, artifacts=validation["artifacts"], reused=True)
        out = self.root / "validation" / uuid4().hex
        outcome, result = self._worker("audit", {"run_dir": str(run)}, out, native=True)
        if result is None:
            return self._observation(False, outcome["state"], error_code="validation_worker_failed")
        if self.cancel_event is not None and self.cancel_event.is_set():
            return self._observation(False, "cancelled", error_code="validation_cancelled")
        artifacts = []
        try:
            if type(result) is not dict or set(result) != {"validation", "artifacts", "resources"}:
                raise ValidationContractError("Native audit result is incomplete or has unknown fields.")
            if type(result["artifacts"]) is not list:
                raise ValidationContractError("Native audit artifact list is malformed.")
            for item in result["artifacts"]:
                if (type(item) is not dict or set(item) not in ({"file", "kind"}, {"file", "kind", "section_id"})
                        or type(item["file"]) is not str or Path(item["file"]).name != item["file"]):
                    raise ValidationContractError("Native audit artifact path or metadata is invalid.")
                artifacts.append(_artifact(out / item["file"], self.task_dir, kind=item["kind"],
                                           **{k: v for k, v in item.items() if k not in {"file", "kind"}}))
            artifacts.append(_artifact(out / "observation.json", self.task_dir, kind="validation_worker_receipt"))
            current_candidate, current_run = self._verified_candidate()
            if self._validation_context(current_candidate, current_run) != context:
                raise ValidationContractError("Candidate or source changed while validation was running.")
            contract = make_contract(result["validation"], context, artifacts, outcome, self.task_dir)
            validation = {**result["validation"], "generation_id": self.generation_id,
                          "revision_id": self.revision_id, **SEMANTIC_FLAGS,
                          "artifacts": artifacts, "contract": contract}
            assessment = verify_validation(validation, context, self.task_dir)
        except (ValidationContractError, ValueError, OSError, TypeError, KeyError) as exc:
            return self._observation(False, "validation_failed", error_code="invalid_validation_contract",
                                     exception_type=type(exc).__name__, artifacts=artifacts,
                                     message="Native audit evidence cannot support validation; failed artifacts are retained.")
        self.state["validation"] = validation
        self._save()
        return self._observation(assessment.passed,
                                 "validated_review_required" if assessment.passed else "validation_failed",
                                 validation=validation, artifacts=validation["artifacts"],
                                 resources={"wall_seconds": outcome["elapsed_seconds"]})


def _adaptive_anchors(rows, xs, py_top, py_bottom):
    """A bounded source corridor; coordinates are never accepted from a model."""
    import numpy as np
    all_rows = np.unique(np.r_[py_top, rows[(rows > py_top) & (rows < py_bottom)], py_bottom])
    all_xs = np.interp(all_rows, rows, xs)
    selected = [0, len(all_rows) - 1]
    error = float("inf")
    for _ in range(62):
        selected.sort()
        residual = np.abs(np.interp(all_rows, all_rows[selected], all_xs[selected]) - all_xs)
        index = int(np.argmax(residual))
        error = float(residual[index])
        if error <= 1.0:
            break
        selected.append(index)
    if error > 1.0:
        return None
    return [[float(all_xs[i]), float(all_rows[i])] for i in sorted(set(selected))]


def estimated_inspection_cpu_seconds(section: dict) -> float:
    """Estimated worker CPU seconds to inspect one section, from its ROI area."""
    left, top, right, bottom = section["roi_px"]
    return INSPECTION_CPU_SECONDS_PER_MEGAPIXEL * (right - left) * (bottom - top) / 1e6


def _write_section_evidence(image, section: dict, entry: dict, out: Path, source_sha: str, artifacts: list):
    """Write the candidate overlay and evidence record of one inspected section."""
    sid = section["id"]
    basename = "section-" + digest_object(sid)[:12]
    _source_overlay(image, section, entry, out / (basename + ".png"))
    write_json(out / (basename + ".json"), entry)
    artifacts.extend([
        {"file": basename + ".png", "kind": "source_candidate_overlay", "section_id": sid,
         "crop_box_px": list(section["roi_px"]), "source_sha256": source_sha, "coordinate_system": "original source pixels; crop shown with identical orientation and scale"},
        {"file": basename + ".json", "kind": "source_candidate_evidence", "section_id": sid,
         "source_sha256": source_sha}])


def _declared_pieces_entry(image, section: dict, source_file: str, details: dict, source_sha: str,
                           implementation_sha: str) -> dict:
    """Inspection record of a multi-piece section: one candidate, the declared pieces.

    The pieces (corridors and height intervals) are caller evidence of which
    drawn curves form the station. The worker reads them with the engine's
    piece reader; it does not search for other contours. If the reader
    refuses a piece, the section has no candidate and its gap is recorded.
    """
    from .ingest import DrawingError, extract_pieces
    entry = {"section_id": section["id"], "source_sha256": source_sha, "x_m": section["x_m"],
             "implementation_sha256": implementation_sha,
             "roi_px": section["roi_px"], "calibration": section["calibration"],
             "candidates": [], "baseline_gaps": [], "retained_diagnostics": {},
             "retained_competing_count": 0, "rejected_trace_hypotheses": [],
             "semantic_identity": "unresolved_human_review_required", **SEMANTIC_FLAGS}
    entry["grid_evidence"] = {"lattice_detected": False, "unique_non_grid_candidate_id": None,
                              "non_grid_competing_components": None,
                              "interpretation": "Declared piece corridors; no grid grammar is applied."}
    try:
        result, diagnostic = extract_pieces(image, section, source_file, details)
    except DrawingError as exc:
        entry["baseline_gaps"] = [{"kind": exc.kind, "message": str(exc), "section_id": section["id"]}]
        entry["retained_diagnostics"] = exc.diagnostics
        return entry
    entry["retained_diagnostics"] = diagnostic
    traces = [trace for piece in diagnostic["pieces"] for trace in (piece["outer"], piece.get("inner")) if trace]
    calibration = section["calibration"]
    ppm, centre, baseline = calibration["pixels_per_metre"], calibration["centerline_px"], calibration["baseline_px"]
    source_points = [[float(centre + y * ppm), float(baseline - z * ppm)]
                     for piece in result["pieces"] for key in ("points_yz_m", "inner_points_yz_m")
                     for y, z in piece.get(key, [])]
    cid = "pieces-" + digest_object({"source": source_sha, "section": section})[:20]
    entry["candidates"].append({
        "candidate_id": cid, "hypothesis": "declared_piece_corridors", "generated_by": ["declared_piece_corridors"],
        "selectable": True, "declared_pieces": True,
        "source_support": {"observed_row_fraction": round(min(t["coverage"] for t in traces), 5),
                           "max_missing_run_px": max(t["max_missing_run_px"] for t in traces),
                           "maximum_step_px_per_row": round(max(t["maximum_step_px_per_row"] for t in traces), 4),
                           "long_component_support_fraction": round(min(t["long_component_support_fraction"] for t in traces), 5),
                           "mean_trace_contrast": round(min(t["mean_trace_contrast"] for t in traces), 5)},
        "grid_supported_hypothesis": False, "non_grid_competing_components": 0,
        "piece_count": len(result["pieces"]), "region_kinds": result["evidence"]["region_kinds"],
        "source_points_px": source_points, "identity_certified": False})
    entry["grid_evidence"]["unique_non_grid_candidate_id"] = cid
    entry["grid_evidence"]["non_grid_competing_components"] = 0
    return entry


def inspect_source_worker(spec_path: Path, section_ids: list[str], out: Path) -> dict:
    """Private worker operation. No labels/reference geometry are opened."""
    import numpy as np
    from PIL import Image, ImageDraw
    from .ingest import (COMPLEXITY_REDUCTION_WARNING, DrawingError, _candidate_evidence, _eligible_trace_mask, _extract_one,
                         _foreground, _read_image, _source_endpoint_hypothesis, _stroke_identity, _trace,
                         drawn_left_of_centreline)
    from .resources import validate_sources
    spec = load_bounded_json(spec_path)
    validate_sources(spec, spec_path.parent)
    image, details = _read_image(spec["source"], spec_path.parent)
    source_sha = digest_file(spec_path.parent / spec["source"]["file"])
    implementation = {name: digest_file(Path(__file__).with_name(name)) for name in
                      ("agent_tools.py", "agent_render_worker.py", "ingest.py", "resources.py", "schema.py",
                       "fonts.py")}
    out.mkdir(parents=True, exist_ok=False)
    artifacts, sections = [], []
    page = Image.fromarray(image).convert("RGB")
    page_draw = ImageDraw.Draw(page)
    for section in spec["sections"]:
        if section["id"] in section_ids:
            page_draw.rectangle(section["roi_px"], outline=(25, 110, 165), width=2)
            page_draw.text(tuple(section["roi_px"][:2]), section["id"], fill=(180, 35, 25))
    page.thumbnail((3000, 3000))
    page.save(out / "source-page.png")
    artifacts.append({"file": "source-page.png", "kind": "source_page", "source_sha256": source_sha,
                      "crop_box_px": [0, 0, image.shape[1], image.shape[0]], "display_note": "Source page with declared ROI boundaries; display derivative only."})
    for section in spec["sections"]:
        sid = section["id"]
        if sid not in section_ids:
            continue
        if "pieces" in section:
            entry = _declared_pieces_entry(image, section, spec["source"]["file"], details, source_sha,
                                           digest_object(implementation))
            _write_section_evidence(image, section, entry, out, source_sha, artifacts)
            sections.append(entry)
            continue
        diagnostic, gaps = {}, []
        if drawn_left_of_centreline(section):
            # An afterbody curve drawn left of the centreline: its candidates come
            # from the mirrored stroke tools (panel assignment, enumerate_strokes).
            sections.append({"section_id": sid, "source_sha256": source_sha, "x_m": section["x_m"],
                             "implementation_sha256": digest_object(implementation),
                             "roi_px": section["roi_px"], "calibration": section["calibration"],
                             "candidates": [], "baseline_gaps": [], "retained_diagnostics": {},
                             "inspection_note": MIRRORED_HALF_NOTE,
                             "grid_evidence": {"lattice_detected": False, "unique_non_grid_candidate_id": None},
                             "semantic_identity": "unresolved_human_review_required", **SEMANTIC_FLAGS})
            continue
        try:
            _, diagnostic = _extract_one(image, section, spec["source"]["file"], details)
        except DrawingError as exc:
            diagnostic = exc.diagnostics
            gaps = [{"kind": exc.kind, "message": str(exc), "section_id": sid}]
        entry = {"section_id": sid, "source_sha256": source_sha, "x_m": section["x_m"],
                 "implementation_sha256": digest_object(implementation),
                 "roi_px": section["roi_px"], "calibration": section["calibration"],
                 "candidates": [], "baseline_gaps": gaps, "retained_diagnostics": diagnostic,
                 "retained_competing_count": diagnostic.get("competing_candidate_count", 0),
                 "semantic_identity": "unresolved_human_review_required", **SEMANTIC_FLAGS}
        bounds = diagnostic.get("pixel_trace_bounds")
        if not bounds:
            entry["grid_evidence"] = {"lattice_detected": False, "unique_non_grid_candidate_id": None}
            sections.append(entry)
            continue
        left, top, right, bottom = bounds
        crop = image[top:bottom, left:right]
        mask, ink, _ = _foreground(crop)
        eligible, _ = _eligible_trace_mask(mask, None, ink)
        grid = _grid_evidence(mask, (left, top))
        entry["grid_evidence"] = grid
        centre = section["calibration"]["centerline_px"] - left
        # The engine's corridor contract covers the actual rounded pixel trace
        # interval. Fractional calibrated endpoints can lie just inside those
        # rows; using them as corridor endpoints incorrectly omits a boundary
        # row. No source geometry or engine threshold is changed here.
        py_top, py_bottom = float(top), float(bottom - 1)
        traces = []
        variants = [("all_contrast_continuity", eligible)]
        high = eligible & (ink >= 127)
        variants.append(("high_contrast_continuity_hypothesis", high))
        # A retained complete alternative can be selected even when it is faint.
        # Its approximate component points constrain only a source re-trace.
        for alternative in diagnostic.get("candidate_evidence", [])[:MAX_CANDIDATES - 2]:
            points = np.asarray(alternative.get("source_points_px", []), dtype=float)
            if len(points) < 2 or alternative.get("vertical_span_fraction", 0) < .88:
                continue
            rr = points[:, 1] - top
            unique = np.unique(rr)
            xx = np.array([np.median(points[rr == row, 0]) - left for row in unique])
            if unique[0] > 5 or unique[-1] < len(mask) - 6:
                continue
            path = np.interp(np.arange(len(mask)), unique, xx)
            corridor = np.abs(np.arange(mask.shape[1])[None, :] - path[:, None]) <= 3
            variants.append(("retained_alternative_source_continuity", eligible & corridor))
        traced_variants = []
        endpoint_variants = []
        # Every interpretation that does not enter the catalog is disclosed
        # with its reason, so an empty catalog explains itself.
        rejected = entry["rejected_trace_hypotheses"] = []
        for hypothesis, candidate_mask in variants:
            try:
                rows, xs, quality = _trace(candidate_mask, ink, centre)
            except DrawingError as exc:
                rejected.append({"hypothesis": hypothesis, "reason": exc.kind})
                continue
            identity = _stroke_identity(mask, ink, rows, xs, (left, top), grid)
            if identity["ruler_continuations"]:
                rejected.append({"hypothesis": hypothesis, "reason": "stroke_identity_unresolved",
                                 "stroke_identity": identity})
                continue
            traced_variants.append((hypothesis, rows, xs, quality, None, None))
            endpoint = _source_endpoint_hypothesis(mask, ink, rows, xs, centre,
                                                    quality["median_stroke_width_px"])
            if endpoint is not None:
                erows, exs = endpoint["rows"], endpoint["xs"]
                revised_quality = {**quality, "observed_row_count": len(erows),
                    "interpolated_row_count": len(mask) - len(erows),
                    "max_missing_run_px": max(int(erows[0]), int(len(mask) - 1 - erows[-1]),
                        int(np.max(np.diff(erows) - 1))),
                    "maximum_step_px_per_row": float(np.max(np.abs(np.diff(exs) / np.diff(erows))))}
                evidence = endpoint["evidence"]
                # Coordinates remain explicitly in original source pixels.
                evidence = {**evidence,
                    "contact_px": [evidence["contact_local_px"][0] + left,
                                   evidence["contact_local_px"][1] + top],
                    "source_run_px": [evidence["source_run_local_px"][0] + left,
                                      evidence["source_run_local_px"][1] + left],
                    "coordinate_origin_px": [left, top]}
                endpoint_variants.append(("source_endpoint_contact_hypothesis", erows, exs,
                                          revised_quality, evidence,
                                          np.interp(np.arange(len(mask)), rows, xs)))
        # Existing alternatives retain priority in the bounded catalog. New
        # interpretations may not crowd a faint rival out of the evidence.
        for hypothesis, rows, xs, quality, endpoint_evidence, parent_dense in traced_variants + endpoint_variants:
            coverage = len(rows) / len(mask)
            max_gap = quality["max_missing_run_px"]
            outcome = {"hypothesis": hypothesis, "observed_row_fraction": round(coverage, 5),
                       "max_missing_run_px": max_gap,
                       "maximum_step_px_per_row": round(quality["maximum_step_px_per_row"], 4)}
            if coverage < .9 or max_gap > max(3, math.ceil(len(mask) * .025)):
                rejected.append({**outcome, "reason": "insufficient_row_coverage"})
                continue
            absolute_rows, absolute_xs = rows + top, xs + left
            anchors = _adaptive_anchors(absolute_rows, absolute_xs, py_top, py_bottom)
            if anchors is None:
                # Typically a trace that jumps between strokes (grid, lettering,
                # another station); it cannot be a bounded selection corridor.
                rejected.append({**outcome, "reason": "not_representable_as_bounded_corridor"})
                continue
            # Deduplicate numerical variants, retaining generation provenance.
            dense = np.interp(np.arange(len(mask)), rows, xs)
            duplicate = next((i for i, t in enumerate(traces)
                              if float(np.max(np.abs(t["dense"] - dense))) < 1.1), None)
            if duplicate is not None:
                entry["candidates"][duplicate]["generated_by"].append(hypothesis)
                continue
            if len(entry["candidates"]) >= MAX_CANDIDATES:
                entry["additional_endpoint_hypotheses_omitted"] = True
                continue
            selection = {"anchors_px": anchors, "half_width_px": 2.75}
            cid = "contour-" + digest_object({"source": source_sha, "section": section,
                                              "selection": selection})[:20]
            try:
                competition = _candidate_evidence(mask, ink, rows, xs, centre, (left, top),
                                                   quality["median_stroke_width_px"], None)
            except DrawingError as exc:
                if exc.kind != "resource_limit":
                    raise
                entry.setdefault("baseline_gaps", []).append({"kind":"resource_limit", "severity":"warning",
                    "section_id":sid, "message":"Candidate competition exceeds inspection budget; use bounded tracing or propose_section."})
                continue
            non_grid = 0
            for alt in competition["candidate_evidence"]:
                p = np.asarray(alt["source_points_px"])
                if not len(p) or not grid["lattice_detected"]:
                    non_grid += 1
                    continue
                dx = np.min(np.abs(p[:, 0, None] - np.asarray(grid["vertical_lines_px"])[None, :]), axis=1)
                dy = np.min(np.abs(p[:, 1, None] - np.asarray(grid["horizontal_lines_px"])[None, :]), axis=1)
                if float(np.mean((dx <= 3) | (dy <= 3))) < .97:
                    non_grid += 1
            eligible_grid = bool(grid["lattice_detected"] and non_grid == 0 and
                                 quality["long_component_support_fraction"] >= .65)
            if eligible_grid:
                # A nearly wholly vertical grid stroke remains ambiguous even
                # if it also has no other non-grid competitor in a blank panel.
                distance = np.min(np.abs((dense + left)[:, None] -
                                        np.asarray(grid["vertical_lines_px"])[None, :]), axis=1)
                eligible_grid = float(np.mean(distance > 3)) >= .20
            candidate = {"candidate_id": cid, "hypothesis": hypothesis,
                         "generated_by": [hypothesis], "selectable": True,
                         "source_support": {"observed_row_fraction": round(coverage, 5),
                                            "max_missing_run_px": max_gap,
                                            "maximum_step_px_per_row": round(quality["maximum_step_px_per_row"], 4),
                                            "long_component_support_fraction": round(quality["long_component_support_fraction"], 5),
                                            "mean_trace_contrast": round(quality["mean_trace_contrast"], 5)},
                         "grid_supported_hypothesis": eligible_grid,
                         "non_grid_competing_components": non_grid,
                         "contour_selection": selection,
                         "source_points_px": [[float(x), float(y)] for x, y in zip(absolute_xs, absolute_rows)],
                         "identity_certified": False}
            if "complexity_reduction" in quality or "evidence_complexity_reduction" in competition:
                candidate["warnings"] = [COMPLEXITY_REDUCTION_WARNING]
            if endpoint_evidence is not None:
                parent = next((t for t in traces
                               if float(np.max(np.abs(t["dense"] - parent_dense))) < 1.1), None)
                candidate["endpoint_evidence"] = {**endpoint_evidence,
                    "centroid_alternative_id": parent["candidate_id"] if parent else None}
                candidate["endpoint_interpretation_requires_review"] = True
            traces.append({"dense": dense, "candidate_id": cid})
            entry["candidates"].append(candidate)
        acceptable = [c for c in entry["candidates"] if c["grid_supported_hypothesis"]]
        # Prefer the best observed continuity only within the fully disclosed
        # grid-supported class. A contrast prior alone never gets this label.
        if acceptable:
            acceptable.sort(key=lambda c: (c["source_support"]["maximum_step_px_per_row"],
                                           -c["source_support"]["observed_row_fraction"]))
            winner = acceptable[0]
            if "endpoint_evidence" not in winner:
                winner["hypothesis"] = "grid_supported_contour_hypothesis"
            grid["unique_non_grid_candidate_id"] = winner["candidate_id"]
            grid["non_grid_competing_components"] = 0
        else:
            grid["non_grid_competing_components"] = min((c["non_grid_competing_components"] for c in entry["candidates"]), default=None)
        _write_section_evidence(image, section, entry, out, source_sha, artifacts)
        sections.append(entry)
    model_artifacts = []
    for artifact in artifacts:
        if artifact["file"].endswith(".png"):
            artifact["model_eligible"] = False
            derivative = _model_observation_image(out / artifact["file"])
            model_artifacts.append({**derivative, "kind": "model_observation",
                                    "section_id": artifact.get("section_id"), "source_sha256": source_sha,
                                    "evidence_kind": artifact["kind"], "crop_box_px": artifact["crop_box_px"]})
    return {"sections": sections, "artifacts": artifacts + model_artifacts, "source_sha256": source_sha,
            "implementation_files_sha256": implementation, "implementation_sha256": digest_object(implementation)}


def _model_observation_image(source: Path) -> dict:
    """Bounded display derivative; never replace or measure from this image."""
    import io
    from PIL import Image
    with Image.open(source) as opened:
        original_size = list(opened.size)
        image = opened.convert("RGB")
    image.thumbnail((1024, 768), Image.Resampling.LANCZOS)
    payload = None
    used_colors = None
    # Quantization is only for the explicitly bounded model observation.  The
    # full-colour evidence and original pixel candidates remain untouched.
    for colors in (256, 128, 64, 32, 16):
        buffer = io.BytesIO()
        image.quantize(colors=colors, method=Image.Quantize.MEDIANCUT).save(buffer, format="PNG", optimize=True)
        if len(buffer.getvalue()) <= 128 * 1024:
            payload, used_colors = buffer.getvalue(), colors
            break
    while payload is None:
        image = image.resize((max(64, int(image.width * .8)), max(64, int(image.height * .8))), Image.Resampling.LANCZOS)
        buffer = io.BytesIO(); image.quantize(colors=16).save(buffer, format="PNG", optimize=True)
        if len(buffer.getvalue()) <= 128 * 1024:
            payload, used_colors = buffer.getvalue(), 16
    target = source.with_name(source.stem + "-model.png")
    target.write_bytes(payload)
    return {"file": target.name, "model_eligible": True, "derivative_of_sha256": digest_file(source),
            "original_pixel_size": original_size, "pixel_size": list(image.size), "palette_colors": used_colors,
            "display_only": True,
            "evidence_limitations": "Downsampled and palette-reduced model observation; faint detail may be obscured. Original source and all candidate evidence remain preserved. Geometry never uses this derivative."}


def _source_overlay(image, section, entry, target):
    from PIL import Image, ImageDraw, ImageFont
    from .fonts import dejavu_sans
    roi = section["roi_px"]
    crop = Image.fromarray(image).crop(roi).convert("RGB")
    scale = min(3, 1300 / max(crop.size))
    crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (crop.width * 2 + 72, crop.height + 210), "white")
    canvas.paste(crop, (24, 75)); canvas.paste(crop, (48 + crop.width, 75))
    draw = ImageDraw.Draw(canvas)
    try:
        font = dejavu_sans(14)
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 12), entry["section_id"] + " | SOURCE HYPOTHESES — HUMAN REVIEW REQUIRED", fill="#183348", font=font)
    draw.text((24, 40), "Untouched crop", fill="#183348", font=font)
    draw.text((48 + crop.width, 40), "Candidate paths and retained alternatives", fill="#183348", font=font)
    def project(point):
        return (48 + crop.width + (point[0] - roi[0]) * scale, 75 + (point[1] - roi[1]) * scale)
    for alternative in entry["retained_diagnostics"].get("candidate_evidence", []):
        for point in alternative.get("source_points_px", []):
            x, y = project(point)
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="#d47a17")
    colors = ["#2f739e", "#4c9b66", "#ae5baf", "#b94545", "#478b8b"]
    for index, candidate in enumerate(entry["candidates"]):
        color = colors[index % len(colors)]
        draw.line([project(p) for p in candidate["source_points_px"]], fill=color, width=1)
        if index < 5:
            draw.text((24, 90 + crop.height + index * 15), candidate["candidate_id"] + " " + candidate["hypothesis"], fill=color, font=font)
    calibration = section["calibration"]
    center, baseline = project((calibration["centerline_px"], calibration["baseline_px"]))
    draw.line((center, 75, center, 75 + crop.height), fill="#5975c0", width=1)
    draw.line((48 + crop.width, baseline, 48 + 2 * crop.width, baseline), fill="#5975c0", width=1)
    draw.text((24, canvas.height - 22),
              f"Orange = retained alternatives; blue datum. Scale {calibration['pixels_per_metre']:.5g} px/m; x={section['x_m']:.5g} m. No truth geometry used.",
              fill="#465b6b", font=font)
    canvas.save(target)
