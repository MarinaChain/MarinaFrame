"""Typed, secret-free tool subprocess for the Rust authoritative controller.

This module never invokes the Python Harness or a model provider. Paths are
trusted CLI configuration. Operation arguments come from a strict protocol and
the existing source-bound DomainTools allowlist. Linux limits are applied by the
Rust supervisor and retained native supervisors; this is not an OS sandbox.
"""
from __future__ import annotations

import argparse
import json
import resource
import shutil
import signal
import sys
import threading
import time
from importlib import metadata
from pathlib import Path

from .agent_tools import DomainTools, _artifact, _model_observation_image
from .provenance import digest_file, digest_object, write_json
from .resources import peak_rss_kib
from .schema import loads_bounded_json
from .validation_contract import implementation_identity as audit_implementation_identity

PROTOCOL = "marinaframe.worker.v1"
OPERATIONS = {"initialize", "observe", "inspect_source", "select_contours",
              "build_provisional", "build_draft", "render_candidate", "validate_candidate",
              # Model investigation tools (investigation_tools.py).
              "view_region", "read_region", "trace_corridor", "trace_from_point", "enumerate_strokes", "assign_station",
              "propose_sheet_setup", "compare_views", "propose_section"}


def implementation_identity():
    root = Path(__file__).resolve().parent
    files = {p.name: digest_file(p) for p in sorted(root.glob("*.py"))}
    versions = {name: metadata.version(name) for name in ("cadquery", "cadquery-ocp", "numpy", "Pillow", "scipy")}
    return digest_object({"files": files, "dependencies": versions, "python": sys.version.split()[0]})


def parse_request(raw):
    value = loads_bounded_json(raw, max_bytes=98_304, max_depth=16,
                              max_nodes=10_000, max_string=8192)
    fields = {"protocol", "request_id", "operation", "arguments",
              "expected_domain_sha256", "expected_worker_sha256"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid worker request fields")
    if value["protocol"] != PROTOCOL or value["operation"] not in OPERATIONS:
        raise ValueError("Unsupported worker protocol or operation")
    rid = value["request_id"]
    if type(rid) is not str or not 1 <= len(rid) <= 128 or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in rid):
        raise ValueError("Invalid request identity")
    if type(value["arguments"]) is not dict:
        raise ValueError("Arguments must be an object")
    for name in ("expected_domain_sha256", "expected_worker_sha256"):
        v = value[name]
        if v is not None and (type(v) is not str or len(v) != 64 or
                              any(c not in "0123456789abcdef" for c in v)):
            raise ValueError("Invalid hash binding")
    if value["operation"] in {"initialize", "observe"} and value["arguments"]:
        raise ValueError("This operation takes no arguments")
    return value


def execute(request, task_root, source_spec, cancel):
    task_root = Path(task_root).absolute()
    if task_root.is_symlink() or not task_root.is_dir():
        raise ValueError("Task root must be an existing ordinary directory")
    # A parent directory may be a symlink (macOS /tmp -> /private/tmp).
    # DomainTools resolves its paths, so artifact paths must use the same form.
    task_root = task_root.resolve()
    implementation = implementation_identity()
    expected = request["expected_worker_sha256"]
    if expected is not None and expected != implementation:
        raise ValueError("Worker implementation changed")
    checkpoint = task_root / "domain/state.json"
    expected = request["expected_domain_sha256"]
    if request["operation"] == "initialize":
        if expected is not None or checkpoint.exists():
            raise ValueError("Initialize requires an absent domain")
    elif expected is None or not checkpoint.is_file() or checkpoint.is_symlink() or digest_file(checkpoint) != expected:
        raise ValueError("Domain checkpoint is missing or changed")
    if cancel.is_set():
        raise InterruptedError("Worker cancelled before operation")
    domain = DomainTools(task_root, Path(source_spec), cancel_event=cancel)
    if request["operation"] in {"initialize", "observe"}:
        result = {"ok": True, "status": "observed", "artifacts": [],
                  "engineering_approved": False, "human_semantic_review_required": True,
                  "tools": domain.catalog()}
    else:
        result = domain.execute(request["operation"], request["arguments"])
    # The controller pins this value from the initialize receipt and later
    # requires every validation contract to carry the pinned value.
    result["audit_implementation_sha256"] = audit_implementation_identity()
    if domain.state.get("validation") is not None:
        result["validation_context"] = domain.validation_context()
    if request["operation"] == "validate_candidate" and isinstance(result.get("validation"), dict):
        validation = result["validation"]
        # Supplemental display derivatives are outside the authoritative native
        # audit directory and do not modify its strict artifact inventory.
        destination = domain.root / "model-observations" / request["request_id"]
        destination.mkdir(parents=True, exist_ok=False)
        observed = []
        for index, artifact in enumerate(validation["artifacts"]):
            if artifact["kind"] != "step_section_cut_comparison":
                continue
            original = task_root / artifact["path"]
            if digest_file(original) != artifact["sha256"]:
                raise ValueError("Section comparison changed")
            copied = destination / f"section-{index:03d}.png"
            shutil.copyfile(original, copied)
            meta = _model_observation_image(copied)
            observed.append(_artifact(destination / meta.pop("file"), task_root,
                kind="model_observation", evidence_kind="step_section_cut_comparison",
                view="section_cut:" + artifact["section_id"], section_id=artifact["section_id"],
                generation_id=domain.generation_id, revision_id=domain.revision_id,
                step_sha256=validation["contract"]["binding"]["step_sha256"],
                authoritative_source_artifact=artifact, **meta))
        result["model_observations"] = observed
    if implementation_identity() != implementation:
        raise ValueError("Worker implementation changed during execution")
    return {"result": result, "domain": domain.describe(),
            "domain_checkpoint_sha256": digest_file(domain.state_path),
            "implementation_sha256": implementation}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--task-root", required=True, type=Path)
    p.add_argument("--source-spec", required=True, type=Path)
    p.add_argument("--response", required=True, type=Path)
    args = p.parse_args(argv)
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    started = time.monotonic()
    request = None
    envelope = {"protocol": PROTOCOL, "request_id": None, "operation": None,
                "execution_state": "failed", "result": None, "domain": None,
                "domain_checkpoint_sha256": None,
                "implementation_sha256": implementation_identity(), "error_code": None}
    try:
        request = parse_request(sys.stdin.buffer.read(98_305))
        envelope.update(request_id=request["request_id"], operation=request["operation"])
        envelope.update(execute(request, args.task_root, args.source_spec, cancel))
        envelope["execution_state"] = "completed"
    except InterruptedError:
        envelope.update(execution_state="cancelled", error_code="worker_cancelled")
    except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
        # Native data and exceptions can include arbitrary source text/paths.
        # Preserve a bounded category, never a raw exception or environment.
        envelope["error_code"] = "worker_boundary_" + type(exc).__name__.lower()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    envelope["resources"] = {
        "wall_seconds": time.monotonic() - started,
        "worker_cpu_seconds": usage.ru_utime + usage.ru_stime,
        "children_cpu_seconds": children.ru_utime + children.ru_stime,
        "worker_peak_rss_kib": peak_rss_kib(usage.ru_maxrss),
        "children_peak_rss_kib": peak_rss_kib(children.ru_maxrss),
        "rss_interpretation": "separate process maxima; not summed process-tree peak"}
    args.response.parent.mkdir(parents=True, exist_ok=True)
    if args.response.exists() or args.response.is_symlink():
        raise SystemExit("Refusing to replace a worker receipt")
    write_json(args.response, envelope)
    print(json.dumps({"protocol": PROTOCOL, "request_id": envelope["request_id"],
                      "execution_state": envelope["execution_state"]}))
    return 0 if envelope["execution_state"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
