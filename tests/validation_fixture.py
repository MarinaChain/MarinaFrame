"""Explicit controlled validator fixture; no native geometry claim is made."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from vessel_reconstruction.agent_tools import DomainTools
from vessel_reconstruction.provenance import digest_file, write_json
from vessel_reconstruction.validation_contract import DISTANCE_TYPE, SECTION_SAMPLING_TEXT, SEMANTICS
from test_agent_tools import drawing


class ControlledValidationDomain(DomainTools):
    """Real capture/cache/finalization code with a deliberately injected audit.

    Only immutable native-run verification and the native audit are doubled.
    Separate integration tests build and independently reimport real STEP.
    """

    def __init__(self, task_dir, *, maximum=0.01, raw_mutator=None, outcome=None):
        task_dir = Path(task_dir)
        source, _ = drawing(task_dir.parent / (task_dir.name + "-source"))
        super().__init__(task_dir, source)
        self.audit_calls = 0
        self.maximum = maximum
        self.raw_mutator = raw_mutator
        self.outcome = outcome
        if not self.state["builds"]:
            spec = self._write_revision()
            run = self.root / "builds" / "controlled"
            run.mkdir(parents=True)
            (run / "model.step").write_bytes(b"CONTROLLED TEST DOUBLE; NOT AN ACTUAL CAD FILE\n")
            sections = [{"id": s["id"], "x_m": s["x_m"], "points_yz_m": [[0.5, 0.0], [1.25, 3.0]],
                         "evidence": {"calibration": s["calibration"]}}
                        for s in self.spec["sections"]]
            result = {"run_id": "1" * 20, "status": "review_required",
                      "review": {"state": "unreviewed", "engineering_approved": False},
                      "provenance": {"submitted_spec_sha256": digest_file(spec)},
                      "exports": {"step": "model.step", "step_units": "mm"},
                      "sections": sections,
                      "metrics": {"length_m": 4.0, "beam_m": 2.5, "depth_m": 3.0, "volume_m3": 21.0}}
            write_json(run / "result.json", result)
            write_json(run / "manifest.json", {"fixture": "controlled native-run test double"})
            candidate = {"id": self.generation_id, "generation_id": self.generation_id,
                         "revision_id": self.revision_id, "path": run.relative_to(task_dir).as_posix(),
                         "valid": True, "status": "review_required", "run_id": result["run_id"]}
            self.state["builds"].append(candidate)
            self.state["last_valid_candidate"] = candidate
            self._save()

    def _verified_candidate(self, *, allow_previous=False):
        candidate = self.state["builds"][-1]
        return candidate, self.task_dir / candidate["path"]

    def _worker(self, operation, request, out, *, native=False):
        assert operation == "audit"
        self.audit_calls += 1
        if self.outcome is not None:
            return deepcopy(self.outcome), None
        candidate, run = self._verified_candidate()
        context = self._validation_context(candidate, run)
        maximum = self.maximum
        reports = [{"section_id": sid, "x_m": info["x_m"], "sample_count": info["sample_count"],
                    "distance_type": DISTANCE_TYPE, "rms_m": maximum, "p95_m": maximum,
                    "max_m": maximum, "max_px": maximum * info["pixels_per_metre"],
                    "source_measurement_uncertainty_m": None, "section_edges": 4}
                   for sid, info in context["section_info"].items()]
        raw = {"geometry_checks_passed": maximum <= 0.0011, "immutable_run_verified": True,
               "geometry_audit": {"source": "independently_reimported_exported_STEP",
                  "step_sha256": context["binding"]["step_sha256"], "step_units": "mm", "reported_units": "m",
                  "valid_shape": True, "solid_count": 1, "shell_count": 1, "closed_shell": True,
                  "metrics": context["engine_metrics"], "relative_metric_error": 0.0,
                  "engineering_approved": False, "human_semantic_review_required": True},
               "sampled_sections": reports, "sampled_section_count": len(reports),
               "total_section_count": len(reports), "section_sampling": SECTION_SAMPLING_TEXT,
               "numeric_reference_truth_used": False, "unresolved_semantics": list(SEMANTICS),
               "human_semantic_review_required": True, "engineering_approved": False}
        if self.raw_mutator:
            self.raw_mutator(raw)
        out.mkdir(parents=True)
        artifacts = []
        for i, sid in enumerate(context["sampling"]["section_ids"]):
            filename = f"section-cut-{i:03d}.png"
            (out / filename).write_bytes(b"CONTROLLED TEST COMPARISON IMAGE BYTES\n" + sid.encode())
            artifacts.append({"file": filename, "kind": "step_section_cut_comparison", "section_id": sid})
        write_json(out / "validation.json", raw)
        artifacts.append({"file": "validation.json", "kind": "step_reimport_validation"})
        result = {"validation": raw, "artifacts": artifacts, "resources": {
            "wall_seconds": 0.0, "cpu_seconds": 0.0, "peak_rss_kib": 1,
            "resource_profile": "linux_rlimit_process_group_v1"}}
        write_json(out / "observation.json", result)
        return {"state": "exited", "exit_code": 0, "elapsed_seconds": 0.0}, result
