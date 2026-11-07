"""Source-bound, typed operations for the hull reconstruction agent.

The model chooses opaque candidates, never Python, paths, or geometry.  A
candidate is a hypothesis about visible ink.  Selecting it remains a semantic
review obligation even when the ordinary engine can construct a valid solid.
All image/native work runs in the existing bounded worker profile.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import sys
from uuid import uuid4

from .isolation import DEFAULT_LIMITS, run_isolated, supervise_process
from .provenance import digest_file, digest_object, safe_relative_file, write_json
from .schema import MAX_SPEC_BYTES, load_bounded_json, loads_bounded_json, validate_spec


DOMAIN_VERSION = "source_bound_tools_v1"
VIEWS = ("body", "plan", "profile", "oblique")
MAX_CANDIDATES = 10
INSPECTION_BATCH = 12
MAX_INSPECTION_BYTES = 24 * 1024 * 1024
SEMANTIC_FLAGS = {"human_semantic_review_required": True, "engineering_approved": False,
                  "identity_certified": False}


class ToolInputError(ValueError):
    """A recoverable rejected action, without arbitrary exception text."""


def _definition(name, description, properties=None, required=()):
    return {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": list(required),
        "additionalProperties": False}}


def _artifact(path: Path, task_dir: Path, *, kind: str, **extra) -> dict:
    relative = path.relative_to(task_dir).as_posix()
    safe_relative_file(task_dir, relative)
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".json": "application/json", ".step": "model/step",
            ".stl": "model/stl"}.get(suffix, "application/octet-stream")
    sha = digest_file(path)
    return {"id": "artifact-" + sha[:24], "sha256": sha, "mime_type": mime,
            "path": relative, "kind": kind, "bytes": path.stat().st_size, **extra}


class DomainTools:
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
        (destination / "submitted_spec.json").write_bytes(raw)
        write_json(destination / "spec.json", captured)
        validation = validate_spec(captured, destination)
        state = {"version": DOMAIN_VERSION, "submitted_spec_sha256": digest_object(spec),
                 "input_spec_sha256": digest_file(destination / "spec.json"), "sources": sources,
                 "revision": 0, "selected": {}, "catalog": {}, "inspection_artifacts": [],
                 "builds": [], "last_valid_candidate": None, "validation": None,
                 "rendered_views": [], "input_errors": validation}
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
        self.spec = load_bounded_json(path)

    @property
    def revision_id(self):
        revision = self.state.get("revision")
        if type(revision) is not int or not 0 <= revision <= 99_999_999:
            raise ValueError("Domain revision must be an exact bounded nonnegative integer.")
        return f"r{revision:04d}"

    @property
    def generation_id(self):
        return "generation-" + digest_object({"source": self.state["input_spec_sha256"],
                                              "selected": self.state["selected"]})[:24]

    def _save(self):
        write_json(self.state_path, self.state)

    def describe(self) -> dict:
        sections = [{"id": s.get("id"), "x_m": s.get("x_m"),
                     "selected_candidate_id": self.state["selected"].get(s.get("id")),
                     "inspected": s.get("id") in self.state["catalog"]}
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
                "catalog_ready": bool(sections) and all(s["inspected"] for s in sections),
                "inspected_sections": inspected, "inspected_section_count": len(ordered),
                "inspected_sections_truncated": len(ordered) > INSPECTION_BATCH,
                "remaining_section_ids": [s["id"] for s in sections if not s["inspected"]],
                "current_candidate": copy.deepcopy(current),
                "last_valid_candidate": copy.deepcopy(self.state["last_valid_candidate"]),
                "validation": copy.deepcopy(self.state["validation"]),
                "rendered_views": list(self.state["rendered_views"]),
                "input_errors": self.state["input_errors"][:32], **SEMANTIC_FLAGS}

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
            _definition("render_candidate", "Reimport a verified exported STEP file and render a named physical view. Output identifies the revision and whether it is an older preserved candidate.",
                        {"view": {"type": "string", "enum": list(VIEWS)}}, ["view"]),
            _definition("validate_candidate", "Verify the current immutable run and independently reimport STEP. Report source-to-CAD section checks and remaining semantic review obligations; never grant engineering approval."),
        ]

    def _arguments(self, name, arguments):
        if not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False)) > 65536:
            raise ToolInputError("Tool arguments must be a bounded JSON object.")
        expected = {"inspect_source": {"section_ids"}, "select_contours": {"selections"},
                    "build_provisional": set(), "render_candidate": {"view"},
                    "validate_candidate": set()}
        if name not in expected:
            raise ToolInputError("Unknown domain operation.")
        if set(arguments) - expected[name]:
            raise ToolInputError("Unsupported tool argument; paths, code, and geometry are not accepted.")
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
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ToolInputError("Another domain action is already running.") from exc
                self.state = load_bounded_json(self.state_path, max_bytes=MAX_INSPECTION_BYTES,
                                               max_nodes=600_000)
                self._verify_inputs()
                self._arguments(tool_name, arguments)
                if self.cancel_event is not None and self.cancel_event.is_set():
                    return self._observation(False, "cancelled", error_code="cancelled")
                method = getattr(self, "_" + tool_name)
                return method(**arguments)
        except ToolInputError as exc:
            return self._observation(False, "rejected", error_code="invalid_tool_arguments", message=str(exc))
        except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
            return self._observation(False, "blocked", error_code="domain_integrity_or_input_error",
                                     exception_type=type(exc).__name__)

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
                         cpu_seconds=90 if native else 45, output_bytes=64 * 1024**2)
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

    def _inspect_source(self, section_ids=None):
        if self.state["input_errors"]:
            return self._observation(False, "blocked", validation_errors=self.state["input_errors"][:32])
        if self.spec.get("input_mode", "calibrated_section_curves") != "calibrated_section_curves":
            return self._observation(False, "blocked", error_code="unsupported_agent_input_mode",
                                     message="Contour tools require calibrated section drawings; the table engine remains available separately.")
        requested = section_ids or [s["id"] for s in self.spec["sections"] if s["id"] not in self.state["catalog"]]
        if not requested:
            requested = [s["id"] for s in self.spec["sections"]]
        ids = requested[:INSPECTION_BATCH]
        missing = [sid for sid in ids if sid not in self.state["catalog"]]
        resources = {}
        if missing:
            out = self.root / "inspections" / uuid4().hex
            outcome, result = self._worker("inspect", {"spec_path": str(self.root / "input/spec.json"),
                                                        "section_ids": missing}, out)
            resources = {"worker_state": outcome["state"], "wall_seconds": outcome["elapsed_seconds"]}
            if result is None:
                return self._observation(False, outcome["state"], error_code="inspection_worker_failed", resources=resources)
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
            # Full diagnostics and coordinates remain in source-bound artifacts.
            item.pop("retained_diagnostics", None)
            sections.append(item)
        page_artifacts = [a for a in self.state["inspection_artifacts"] if
                          a["kind"] == "source_page" or a.get("evidence_kind") == "source_page"][-2:]
        observation = self._observation(True, "observed", sections=sections, resources=resources,
            returned_section_ids=list(ids), remaining_requested_section_ids=requested[INSPECTION_BATCH:],
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
        changed = selected != self.state["selected"]
        if changed:
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
        for role in self.state["sources"]:
            spec[role]["file"] = os.path.relpath(self.root / "input" / self.state["sources"][role]["file"], directory)
        for section in spec["sections"]:
            cid = self.state["selected"].get(section["id"])
            if cid is None:
                continue
            candidate = next(c for c in self.state["catalog"][section["id"]]["candidates"] if c["candidate_id"] == cid)
            section["contour_selection"] = copy.deepcopy(candidate["contour_selection"])
            prior = section.get("evidence", "Caller-supplied calibration.")
            section["evidence"] = (prior[:7000] + " Provisional source-bound agent/policy selection " + cid +
                                    "; excluded strokes retained; human semantic review required.")
        write_json(directory / "spec.json", spec)
        write_json(directory / "selection.json", {"revision_id": self.revision_id,
                   "generation_id": self.generation_id, "selected": self.state["selected"],
                   "source_sha256": self.state["sources"], **SEMANTIC_FLAGS})
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
                     "run_id": result.get("run_id") if result else None,
                     "gaps": result.get("gaps", [])[:64] if result else [{"kind": outcome.get("error_code", outcome["state"])}],
                     "metrics": result.get("metrics", {}) if result else {}, **SEMANTIC_FLAGS}
        self.state["builds"].append(candidate)
        if valid:
            self.state["last_valid_candidate"] = candidate
        self.state.update(validation=None, rendered_views=[])
        self._save()
        artifacts = []
        if result:
            artifacts.append(_artifact(out / "result.json", self.task_dir, kind="immutable_engine_record"))
            if valid:
                artifacts.extend(_artifact(out / result["exports"][key], self.task_dir, kind="provisional_" + key)
                                 for key in ("step", "stl", "mesh") if key in result["exports"])
        return self._observation(valid, candidate["status"], candidate=candidate,
                                 validation_errors=candidate["gaps"], artifacts=artifacts,
                                 resources=outcome.get("resources", {}), changed=True,
                                 last_valid_preserved=self.state["last_valid_candidate"] is not None)

    def _verified_candidate(self, *, allow_previous=False):
        from .run_record import verify_run
        candidate = next((b for b in reversed(self.state["builds"]) if b["generation_id"] == self.generation_id
                          and b["revision_id"] == self.revision_id), None)
        if not candidate or candidate.get("valid") is not True:
            if allow_previous:
                candidate = self.state["last_valid_candidate"]
            if not candidate or candidate.get("valid") is not True:
                raise ToolInputError("No valid provisional STEP exists for this revision; build or revise the source selections.")
        path = safe_relative_file(self.task_dir, candidate["path"] + "/result.json").parent
        verification = verify_run(path)
        if verification.get("valid") is not True:
            raise ToolInputError("Candidate evidence changed or failed immutable-run verification.")
        return candidate, path

    def _render_candidate(self, view):
        candidate, run = self._verified_candidate(allow_previous=True)
        out = self.root / "renders" / uuid4().hex
        outcome, result = self._worker("render", {"run_dir": str(run), "view": view}, out, native=True)
        if result is None:
            return self._observation(False, outcome["state"], error_code="render_worker_failed")
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
                                                      **{k: v for k, v in result["model_observation"].items() if k != "file"})],
                                 resources={"wall_seconds": outcome["elapsed_seconds"]})

    def _validation_context(self, candidate, run):
        from .validation_contract import build_context
        return build_context(self.task_dir, self.root, self.state, self.spec, candidate, run)

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
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
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


def _grid_evidence(mask, origin):
    """Conservative repeated orthogonal lattice detection, not ink identity.

    At least three near-equally spaced long lines on EACH axis are required.
    A lone/double faint contour is never classified as a grid by darkness.
    This helper only labels evidence and proposes a selection; it does not
    change the baseline engine's mask, ambiguity gate, or drawing bytes.
    """
    import numpy as np
    from .ingest import _runs
    h, w = mask.shape
    horizontal = []
    for r in range(h):
        runs = _runs(mask[r])
        if any(b - a >= .72 * w for a, b in runs):
            horizontal.append(r)
    def groups(values):
        if not values:
            return []
        array = np.asarray(values)
        return [float(np.median(g)) for g in np.split(array, np.flatnonzero(np.diff(array) > 2) + 1)
                if len(g) <= 8]
    ys = groups(horizontal)
    vertical = []
    if len(ys) >= 3:
        low, high = int(ys[0]), int(ys[-1]) + 1
        vertical = np.flatnonzero(np.mean(mask[low:high], axis=0) >= .82).tolist()
    xs = groups(vertical)
    def regular(values):
        if not 3 <= len(values) <= 32:
            return False
        delta = np.diff(values)
        return bool(np.median(delta) >= 8 and np.max(np.abs(delta - np.median(delta))) <= max(2, .12 * np.median(delta)))
    found = regular(xs) and regular(ys)
    return {"method": "repeated_orthogonal_lattice_v1", "lattice_detected": found,
            "vertical_lines_px": [round(v + origin[0], 3) for v in xs] if found else [],
            "horizontal_lines_px": [round(v + origin[1], 3) for v in ys] if found else [],
            "minimum_lines_per_axis": 3, "unique_non_grid_candidate_id": None,
            "non_grid_competing_components": None,
            "interpretation": "Geometric grid hypothesis only; overlap with a true contour cannot be semantically certified."}


def inspect_source_worker(spec_path: Path, section_ids: list[str], out: Path) -> dict:
    """Private worker operation. No labels/reference geometry are opened."""
    import numpy as np
    from PIL import Image, ImageDraw
    from .ingest import (DrawingError, _candidate_evidence, _eligible_trace_mask, _extract_one,
                         _foreground, _read_image, _source_endpoint_hypothesis, _trace)
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
                      "display_note": "Source page with declared ROI boundaries; display derivative only."})
    for section in spec["sections"]:
        sid = section["id"]
        if sid not in section_ids:
            continue
        diagnostic, gaps = {}, []
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
            competition = _candidate_evidence(mask, ink, rows, xs, centre, (left, top),
                                               quality["median_stroke_width_px"], None)
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
        basename = "section-" + digest_object(sid)[:12]
        _source_overlay(image, section, entry, out / (basename + ".png"))
        write_json(out / (basename + ".json"), entry)
        artifacts.extend([
            {"file": basename + ".png", "kind": "source_candidate_overlay", "section_id": sid,
             "source_sha256": source_sha, "coordinate_system": "original source pixels; crop shown with identical orientation and scale"},
            {"file": basename + ".json", "kind": "source_candidate_evidence", "section_id": sid,
             "source_sha256": source_sha}])
        sections.append(entry)
    model_artifacts = []
    for artifact in artifacts:
        if artifact["file"].endswith(".png"):
            artifact["model_eligible"] = False
            derivative = _model_observation_image(out / artifact["file"])
            model_artifacts.append({**derivative, "kind": "model_observation",
                                    "section_id": artifact.get("section_id"), "source_sha256": source_sha,
                                    "evidence_kind": artifact["kind"]})
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
