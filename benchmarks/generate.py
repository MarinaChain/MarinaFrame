"""Render independently specified hull half-sections into calibrated image panels.

The parser receives only drawing.png and spec.json. Known answers, the rendering
seed, and procedural parameters are written to ground_truth.json, in a sibling
private_labels directory by suite generation. Calibration is explicitly assisted.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCHEMA_VERSION = "1.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trap(y, x):
    return float(np.trapezoid(y, x))


def section_volume(sections: list[dict]) -> float:
    """Independent trapezoidal integration of explicit sections, both hull sides."""
    ordered = sorted(sections, key=lambda s: s["x_m"])
    areas = []
    for s in ordered:
        p = np.asarray(s["points_yz_m"], dtype=float)
        order = np.argsort(p[:, 1])
        areas.append(2 * _trap(p[order, 0], p[order, 1]))
    return _trap(areas, [s["x_m"] for s in ordered])


def _normalise_sections(sections: Iterable[dict]) -> list[dict]:
    result = []
    for i, s in enumerate(sections):
        p = np.asarray(s.get("points_yz_m", s.get("points_yz", [])), dtype=float)
        if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3:
            raise ValueError("Each section needs >=3 [y,z] points")
        if not np.isfinite(p).all() or np.any(p[:, 0] < -1e-9):
            raise ValueError("Half-section points must be finite with y >= 0")
        if np.any(np.diff(p[:, 1]) <= 0):
            raise ValueError("Each half-section must be strictly increasing in z")
        result.append({"id": s.get("id", f"frame-{i:02d}"),
                       "x_m": float(s["x_m"]), "points_yz_m": p.tolist()})
    if len(result) < 3 or np.any(np.diff([s["x_m"] for s in result]) <= 0):
        raise ValueError("Need >=3 sections in strictly increasing x order")
    return result


def generate_section_sheet(
    sections: Iterable[dict], output_dir: str | Path, *,
    vessel_id: str = "example", seed: int = 0, style: str = "clean",
    source_url: str | None = None, source_license: str = "CC0-1.0",
    reference_volume_m3: float | None = None,
    label_dir: str | Path | None = None,
    provenance: dict | None = None,
    missing_curve_index: int | None = None,
) -> dict:
    """Create drawing/spec and a physically separate answer file.

    `sections` uses x_m and points_yz_m=[[half_breadth,elevation],...].
    Styles: clean, drafting (alternate clean), degraded (moderate scan noise).
    No parameter, width, point, or source-CAD path enters the inference spec.
    """
    if style not in {"clean", "drafting", "degraded"}:
        raise ValueError(f"Unsupported rendering style: {style}")
    sections = _normalise_sections(sections)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / 'drawing.png').exists() or (output_dir / 'spec.json').exists():
        raise FileExistsError('Generated case already exists; choose a new destination to preserve frozen inputs')
    labels = Path(label_dir) if label_dir else output_dir.parent / "private_labels" / output_dir.name
    labels.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    all_points = np.concatenate([s["points_yz_m"] for s in sections])
    max_y = float(np.max(all_points[:, 0]))
    z_min = float(np.min(all_points[:, 1]))
    z_max = float(np.max(all_points[:, 1]))
    if max_y <= 0 or z_max <= z_min:
        raise ValueError("Degenerate envelope cannot be rendered")
    cols, panel_w, panel_h = 5, 310, 350
    top, left, plot_w, plot_h = 80, 24, 245, 272
    rows = math.ceil(len(sections) / cols)
    ppm = min(plot_w / (max_y * 1.07), plot_h / (z_max - z_min))
    image = Image.new("L", (cols * panel_w + 2 * left, rows * panel_h + top + 30), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((left, 13), f"{vessel_id} | calibrated half-section drawing | elevations and x stations in metres", fill=30, font=font)
    draw.text((left, 32), "Each viewport: one starboard contour. Port/starboard symmetry and flat terminal closure are assumptions.", fill=75, font=font)
    draw.text((left, 50), f"Scale: {ppm:.6f} pixels/metre. Viewports and scale supplied by an operator.", fill=75, font=font)
    spec_sections = []
    for i, section in enumerate(sections):
        col, row = i % cols, i // cols
        px = left + col * panel_w
        py = top + row * panel_h
        cx = float(px + 24)
        baseline = float(py + 302 + z_min * ppm)
        draw.text((px + 2, py), f"{section['id']}   x = {section['x_m']:.5g} m", fill=30, font=font)
        p = np.asarray(section["points_yz_m"])
        roi = [px + 18, py + 19, px + panel_w - 10, py + 310]
        grid_color = 216 if style != "drafting" else 195
        axis_color = 176
        # Grid and centerline are deliberately lighter than the hull stroke.
        for z in np.linspace(z_min, z_max, 6):
            yy = baseline - z * ppm
            draw.line([(cx, yy), (cx + plot_w, yy)], fill=grid_color, width=1)
        for y in np.linspace(0, max_y, 5):
            xx = cx + y * ppm
            draw.line([(xx, baseline-z_min*ppm), (xx, baseline-z_max*ppm)], fill=grid_color, width=1)
        draw.line([(cx, py + 24), (cx, py + 305)], fill=axis_color, width=1)
        draw.line([(cx, baseline-z_min*ppm), (cx+plot_w, baseline-z_min*ppm)], fill=axis_color, width=1)
        points = [(cx + float(y) * ppm, baseline - float(z) * ppm) for y, z in p]
        if i != missing_curve_index:
            color = 22 if style == "clean" else (45 if style == "drafting" else 35)
            draw.line(points, fill=color, width=2, joint="curve")
        draw.text((px + 3, py + 318), f"z: {p[0,1]:.4g} to {p[-1,1]:.4g} m", fill=80, font=font)
        spec_sections.append({"id": section["id"], "x_m": section["x_m"],
            "roi_px": roi, "calibration": {"centerline_px": cx,
            "baseline_px": baseline, "pixels_per_metre": ppm},
            "z_min_m": float(p[0, 1]), "z_max_m": float(p[-1, 1]),
            "evidence": "Operator-supplied section viewport, station, vertical extent and pixel scale; contour inferred from image pixels."})
    degradation = None
    if style == "degraded":
        a = np.asarray(image, dtype=np.float32)
        # Fixed, moderate scanner degradation. No geometry-dependent tuning.
        h, w = a.shape
        yy, xx = np.mgrid[:h, :w]
        paper = 6.0 * (xx / max(w - 1, 1)) + 3.0 * np.sin(yy / 240.0)
        a = np.clip(a - paper + rng.normal(0.0, 4.5, a.shape), 0, 255)
        sparse = rng.random(a.shape) < 0.0006
        a[sparse] = rng.uniform(35, 140, int(sparse.sum()))
        image = Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=0.42))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=78)
        image = Image.open(io.BytesIO(buf.getvalue())).convert("L")
        degradation = {"gaussian_noise_sigma": 4.5, "dark_speckle_probability": 0.0006,
                       "gaussian_blur_radius_px": 0.42, "jpeg_quality": 78,
                       "paper_gradient_max": 9.0, "rotation": 0}
    image_path = output_dir / "drawing.png"
    # Publish the completed encoded image atomically. A watched workspace may
    # copy newly created files while Pillow is still encoding large scans.
    encoded = io.BytesIO()
    image.save(encoded, format='PNG', optimize=True)
    fd, temporary = tempfile.mkstemp(prefix='.drawing-', suffix='.tmp', dir=output_dir)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(encoded.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, image_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    spec = {"schema_version": SCHEMA_VERSION, "vessel_id": vessel_id,
            "source": {"file": "drawing.png", "url": source_url, "license": source_license},
            "units": "m", "symmetry": "port_starboard",
            "symmetry_evidence": "Declared benchmark assumption, not inferred: mirror the observed starboard half-sections; engineering review required.",
            "end_closure": "flat_at_terminal_stations", "sections": spec_sections,
            "components": []}
    spec_path = output_dir / "spec.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    truth = {"schema_version": SCHEMA_VERSION, "vessel_id": vessel_id,
             "sections": sections, "reference_volume_m3": reference_volume_m3 if reference_volume_m3 is not None else section_volume(sections),
             "reference_volume_method": "Independent numerical integration of known half-section ordinates, doubled for symmetry",
             "beam_m": 2 * max_y, "length_m": sections[-1]["x_m"] - sections[0]["x_m"],
             "depth_m": z_max-z_min, "render_style": style, "render_seed": seed,
             "degradation": degradation, "image_sha256": sha256(image_path),
             "spec_sha256": sha256(spec_path), "source_provenance": provenance or {},
             "expected_outcome": "blocked" if missing_curve_index is not None else "reconstruct",
             "assistance": ["section identity", "x station", "viewport", "pixel scale", "vertical extent", "port/starboard symmetry", "flat terminal closure"],
             "assistance_excludes": ["curve points", "shape parameters", "ground-truth CAD", "target volume"]}
    truth_path = labels / "ground_truth.json"
    truth_path.write_text(json.dumps(truth, indent=2) + "\n")
    return {"spec": str(spec_path), "image": str(image_path), "ground_truth": str(truth_path),
            "image_sha256": truth["image_sha256"], "spec_sha256": truth["spec_sha256"]}


def procedural_sections(seed: int, family: str, *, stations: int = 25, samples: int = 129) -> tuple[list[dict], float, dict]:
    """Deterministic independent hull definitions used only by data production.

    Finite end sections intentionally represent truncated hulls with end caps.
    The held-out families use different equations from the development family.
    """
    rng = np.random.default_rng(seed)
    length = float(rng.uniform(22, 65))
    beam = float(rng.uniform(5.5, 13.0))
    depth = float(rng.uniform(2.5, 6.0))
    end_fraction = float(rng.uniform(0.06, 0.13))
    flare = float(rng.uniform(0.02, 0.15))
    def breadth(u, t):
        if family == "development_wigley":
            envelope = end_fraction + (1-end_fraction) * (1-(2*u-1)**2)
            profile = np.sqrt(np.maximum(0, 2*t-t*t))
        elif family == "holdout_multichine":
            # Piecewise-linear section geometry and skewed sine longitudinal law.
            skew = 0.12 * math.sin(seed)
            v = np.clip(u + skew*u*(1-u), 0, 1)
            envelope = end_fraction + (1-end_fraction)*np.sin(np.pi*v)**0.72
            knots = np.array([0, 0.17, 0.43, 0.76, 1])
            widths = np.array([0, 0.42, 0.78, 0.91, 1.0])
            profile = np.interp(t, knots, widths)
        elif family == "holdout_roundflare":
            envelope = end_fraction + (1-end_fraction) * np.exp(-((u-0.49)/0.46)**4)
            profile = np.sin(np.pi*t/2)**(0.48+0.15*math.cos(seed))
        else:
            raise ValueError(f"Unknown family {family}")
        return beam/2 * envelope * profile * (1+flare*t*t*(0.6+0.4*np.cos(2*np.pi*u)))
    def build(nx, nz):
        us = np.linspace(0, 1, nx)
        ts = np.linspace(0, 1, nz)
        return [{"id": f"frame-{i:02d}", "x_m": float(length*u),
                 "points_yz_m": np.column_stack((breadth(u, ts), depth*ts)).tolist()}
                for i, u in enumerate(us)]
    sections = build(stations, samples)
    # Dense independent integration, not the sparse CAD loft's own volume.
    reference = section_volume(build(801, 1025))
    return sections, reference, {"family": family, "seed": seed,
            "parameters": {"length_m": length, "beam_parameter_m": beam, "depth_m": depth,
                           "end_fraction": end_fraction, "flare": flare},
            "end_caps": "finite station ends explicitly close the cropped model"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/generated/development"))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--style", choices=["clean", "drafting", "degraded"], default="clean")
    parser.add_argument("--family", default="development_wigley")
    args = parser.parse_args()
    sections, volume, provenance = procedural_sections(args.seed, args.family)
    print(json.dumps(generate_section_sheet(sections, args.out, vessel_id=f"{args.family}-{args.seed}",
          seed=args.seed, style=args.style, reference_volume_m3=volume, provenance=provenance), indent=2))

if __name__ == "__main__":
    main()
