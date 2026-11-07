"""Apply the authorized ROI-only intake amendment, preserving the first seal.

No inference code or reference geometry is imported or decoded. The only numeric
transformation is a conservative conversion of crop rectangles to pixel integers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil


ROOT = Path("/tmp/marinaframe-v04-independent")
ORIGINAL = "6489faceb15ebd5a75d12a06f4fc7a09de63000557454488453e9c4c4db0d196"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, obj):
    Path(p).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n")


def rows(root):
    return [{"path": str(p.relative_to(root)), "bytes": p.stat().st_size,
             "sha256": sha(p)} for p in sorted(root.rglob("*")) if p.is_file()]


def tree_digest(files):
    return hashlib.sha256("\n".join(
        f'{r["path"]}\t{r["sha256"]}' for r in files
    ).encode()).hexdigest()


def main():
    source = ROOT / "inference"
    destination = ROOT / "inference_v2"
    public = ROOT / "public_v2"
    old_seal = json.loads((ROOT / "public/seal_receipt.json").read_text())
    if old_seal["input_tree_sha256"] != ORIGINAL or rows(source) != old_seal["files"]:
        raise ValueError("Original inference seal changed")
    destination.mkdir(exist_ok=False)
    public.mkdir(exist_ok=False)
    changes = []
    for original in sorted(source.rglob("*")):
        if not original.is_file():
            continue
        amended = destination / original.relative_to(source)
        amended.parent.mkdir(parents=True, exist_ok=True)
        if original.name != "spec.json":
            shutil.copy2(original, amended)
            continue
        spec = json.loads(original.read_text())
        changed = False
        for section in spec.get("sections", []):
            old = section.get("roi_px")
            if old is None:
                continue
            new = [math.floor(old[0]), math.floor(old[1]),
                   math.ceil(old[2]), math.ceil(old[3])]
            if any(type(a) is not int or a != b for a, b in zip(old, new)):
                changes.append({"case_id": spec["vessel_id"], "section_id": section["id"],
                                "before": old, "after": new})
                changed = True
            section["roi_px"] = new
        if changed:
            write(amended, spec)
        else:
            shutil.copy2(original, amended)
        old_spec = json.loads(original.read_text())
        new_spec = json.loads(amended.read_text())
        for a, b in zip(old_spec.get("sections", []), new_spec.get("sections", [])):
            a.pop("roi_px", None)
            b.pop("roi_px", None)
        if old_spec != new_spec:
            raise ValueError("Amendment changed a non-ROI field")
    now = datetime.now(timezone.utc).isoformat()
    amendment = {
        "created_utc": now,
        "authorized_by": "parent implementation coordinator, before its implementation freeze",
        "reason": "The evaluator's schema-only check missed the integer-pixel ROI intake requirement.",
        "transformation": "roi_px only: floor left/top; ceil right/bottom; JSON integers",
        "original_input_tree_sha256": ORIGINAL,
        "original_seal_receipt_sha256": sha(ROOT / "public/seal_receipt.json"),
        "original_legacy_output_lock_sha256": sha(ROOT / "legacy_runs_001/legacy_output_lock.json"),
        "original_legacy_attempts_preserved": 30,
        "images_unchanged": True,
        "calibration_stations_extents_unchanged": True,
        "reference_geometry_and_gates_unchanged": True,
        "accuracy_feedback_to_implementation": False,
        "numeric_scoring_performed": False,
        "changes": changes,
    }
    write(public / "input_format_amendment.json", amendment)
    manifest = json.loads((ROOT / "public/input_manifest.json").read_text())
    manifest.update({"created_utc": now, "input_format_revision": 2,
                     "original_input_tree_sha256": ORIGINAL,
                     "amendment": "ROI integer intake conversion only; original preflight attempts retained"})
    write(public / "input_manifest.json", manifest)
    files = rows(destination)
    seal = {
        **old_seal,
        "schema_version": "marinaframe-v04-independent-seal-2",
        "sealed_utc": now,
        "files": files,
        "input_tree_sha256": tree_digest(files),
        "input_manifest_sha256": sha(public / "input_manifest.json"),
        "original_input_tree_sha256": ORIGINAL,
        "original_seal_receipt_sha256": sha(ROOT / "public/seal_receipt.json"),
        "input_format_amendment_sha256": sha(public / "input_format_amendment.json"),
        "format_adapter_sha256": sha(__file__),
        "production_solver_executed_before_seal": True,
        "execution_before_v2_seal": "30 retained original-format legacy preflight attempts; no geometry scoring",
        "production_solver_source_inspected": False,
        "reference_geometry_and_gates_unchanged": True,
        "new_implementation_frozen_at_amendment": False,
    }
    write(public / "seal_receipt.json", seal)
    shutil.copy2(ROOT / "public/source_provenance.json", public / "source_provenance.json")
    shutil.copy2(__file__, public / "format_adapter.py")
    print(json.dumps({"sealed_utc": now, "files": len(files), "roi_rectangles_amended": len(changes),
                      "input_root": str(destination), "input_tree_sha256": seal["input_tree_sha256"],
                      "reference_tree_sha256": seal["reference_tree_sha256"],
                      "seal_receipt_sha256": sha(public / "seal_receipt.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
