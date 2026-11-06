"""Preserved minimal reproducers for the original contrast and feature defects.

Run once against the frozen base blobs with --baseline, then against current
source. Both reports include the actual exported and independently cut STEP.
This is a defect reproduction, not a held-out generalization benchmark.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import types

import numpy as np
from PIL import Image, ImageDraw

BASE_REVISION = "7b1a736a0b6c800f8d6dcfe6d59729731b8d7f11"


def _implementations(baseline: bool):
    if not baseline:
        from vessel_reconstruction import ingest, geometry
        hashes = {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                  for module in (ingest, geometry)}
        return ingest, geometry, hashes
    modules, hashes = [], {}
    repo = Path(__file__).resolve().parents[1]
    # Deliberately fixed to the known initial revision, never caller-supplied
    # executable source. No baseline fixes or changed expectations are applied.
    for name in ("ingest", "geometry"):
        source = subprocess.run(["git", "show", f"{BASE_REVISION}:src/vessel_reconstruction/{name}.py"],
                                cwd=repo, capture_output=True, check=True).stdout
        hashes[f"{name}.py"] = hashlib.sha256(source).hexdigest()
        module = types.ModuleType(f"vessel_reconstruction._frozen_base_{name}")
        module.__package__ = "vessel_reconstruction"
        exec(compile(source, f"git:{BASE_REVISION}/{name}.py", "exec"), module.__dict__)
        modules.append(module)
    return *modules, hashes


def run(out: Path, *, baseline: bool = False) -> dict:
    if out.exists():
        raise FileExistsError("Choose a fresh directory; retain the existing reproduction evidence")
    out.mkdir(parents=True)
    ingest, geometry, source_hashes = _implementations(baseline)
    report = {"implementation": "frozen_base" if baseline else "current_worktree",
              "base_revision": BASE_REVISION, "source_hashes": source_hashes,
              "mixed_contrast": [], "purpose": "Original minimal defect reproduction; not a held-out benchmark"}
    for faint in [15, 80, 120, 150, 180, 210]:
        image = Image.new("RGB", (420, 420), "white")
        draw = ImageDraw.Draw(image)
        draw.line((180, 60, 180, 360), fill=(15, 15, 15), width=3)
        draw.line((270, 60, 270, 360), fill=(faint,) * 3, width=3)
        name = f"mixed-contrast-{faint}.png"
        image.save(out / name)
        spec = {"units": "m", "source": {"file": name}, "sections": [{
            "id": "s0", "x_m": 0, "roi_px": [65, 40, 350, 375],
            "calibration": {"centerline_px": 90, "baseline_px": 360, "pixels_per_metre": 60},
            "z_min_m": 0, "z_max_m": 5,
        }]}
        result = ingest.extract_sections(spec, out)
        (out / f"mixed-contrast-{faint}.spec.json").write_text(json.dumps(spec, indent=2) + "\n")
        (out / f"mixed-contrast-{faint}.result.json").write_text(json.dumps(result, indent=2) + "\n")
        accepted = bool(result["sections"])
        report["mixed_contrast"].append({
            "outer_intensity": faint, "accepted": accepted,
            "gaps": [g["kind"] for g in result["gaps"]],
            "confidence": result["sections"][0]["confidence"] if accepted else None,
            "median_half_breadth_m": float(np.median(np.asarray(result["sections"][0]["points_yz_m"])[:, 0])) if accepted else None,
            "retained_competing_candidates": result["diagnostics"]["sections"]["s0"].get("competing_candidate_count"),
        })
    z = np.linspace(0, 4, 129)
    y = np.ones_like(z)
    y[2] = 3.
    sections = [{"id": f"s{i}", "x_m": x, "points_yz_m": np.column_stack((y, z)).tolist()}
                for i, x in enumerate([0., 5., 10.])]
    peak_out = out / "narrow-peak"
    peak_out.mkdir()
    started = time.perf_counter()
    shape, normalized = geometry.build_hull(sections)
    geometry.export_geometry(shape, peak_out)
    points = np.asarray(normalized[0]["cad_points_yz_m"])
    from benchmarks.audit_geometry_hardening import audit_step, analytic_fixture
    audit = audit_step(peak_out / "model.step", analytic_fixture("off_grid_narrow_peak"))
    (peak_out / "source_sections.json").write_text(json.dumps(sections, indent=2) + "\n")
    (peak_out / "normalized_sections.json").write_text(json.dumps(normalized, indent=2) + "\n")
    (peak_out / "actual_step_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    report["narrow_peak"] = {
        "reference_volume_m3": 81.25, "reference_beam_m": 6.,
        "observed": geometry.metrics_for(shape),
        "maximum_lost_half_breadth_m": float(np.max(np.abs(np.interp(z, points[:, 1], points[:, 0]) - y))),
        "actual_step_maximum_station_error_m": audit["maximum_station_error_m"],
        "actual_step_maximum_between_station_error_m": audit["maximum_between_station_error_m"],
        "actual_step_comparator_complete": audit["complete"],
        "actual_step_gate_passed": audit["passed"],
        "wall_seconds": time.perf_counter() - started,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true", help="Run the unchanged source blobs at the fixed original revision")
    args = parser.parse_args()
    print(json.dumps(run(args.out, baseline=args.baseline), indent=2))
