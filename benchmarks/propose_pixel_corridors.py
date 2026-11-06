"""Create explicitly assisted pixel-corridor proposals for operator review.

This is a separate, opt-in proposal utility, not automatic contour identity.
It reads only a source raster and its calibration specification. It cannot
access benchmark labels or prior extracted curves. Darkness selects a proposal,
so every output remains an unvalidated assistant proposal requiring review.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw


def _runs(row):
    values = np.flatnonzero(row)
    return np.split(values, np.flatnonzero(np.diff(values) > 1) + 1) if len(values) else []


def _coarse_anchors(rows: np.ndarray, x: np.ndarray, error_px: float) -> list[list[float]]:
    kept = {0, len(rows) - 1}
    pending = [(0, len(rows) - 1)]
    while pending:
        first, last = pending.pop()
        if last <= first + 1:
            continue
        prediction = x[first] + (x[last] - x[first]) * (rows[first + 1:last] - rows[first]) / (rows[last] - rows[first])
        errors = np.abs(x[first + 1:last] - prediction)
        position = int(np.argmax(errors))
        if errors[position] > error_px:
            at = first + 1 + position
            kept.add(at)
            pending.extend(((first, at), (at, last)))
    if len(kept) > 64:
        raise ValueError("More than 64 coarse anchors are needed; inspect and select this panel manually")
    return [[float(x[i]), float(rows[i])] for i in sorted(kept)]


def propose(spec_path: Path, out: Path, *, luminance_max: float = 128,
            approximation_px: float = 2., half_width_px: float = 6.) -> dict:
    if out.exists():
        raise FileExistsError("Choose a fresh proposal directory; preserve earlier assistance attempts")
    if not 0 < luminance_max < 255 or not 0 < approximation_px < half_width_px <= 128:
        raise ValueError("Invalid bounded proposal parameters")
    started = time.perf_counter()
    raw_spec = spec_path.read_bytes()
    spec = json.loads(raw_spec)
    image_path = spec_path.parent / spec["source"]["file"]
    raw_source = image_path.read_bytes()
    image = Image.open(image_path).convert("RGB")
    rgb = np.asarray(image)
    luminance = rgb @ np.asarray([.2126, .7152, .0722])
    proposed = copy.deepcopy(spec)
    records = []
    for section in proposed["sections"]:
        calibration = section["calibration"]
        left, top, right, bottom = section["roi_px"]
        centre = calibration["centerline_px"]
        baseline, ppm = calibration["baseline_px"], calibration["pixels_per_metre"]
        first = max(top, int(round(baseline - section["z_max_m"] * ppm)))
        last = min(bottom - 1, int(round(baseline - section["z_min_m"] * ppm)))
        x0 = max(left, int(np.floor(centre)))
        seen_rows, positions, ambiguous_rows = [], [], []
        for row in range(first, last + 1):
            candidates = []
            for run in _runs(luminance[row, x0:right] < luminance_max):
                if not len(run) or len(run) > max(12, (right - x0) * .2):
                    continue
                position = float(np.mean(run)) + x0
                candidates.append(position)
            # Exclude the declared axis only when another distinct dark stroke
            # is visible. A sole source stroke approaching the centreline may
            # be a measured keel; deleting it would invent a proposal gap.
            if len(candidates) > 1:
                candidates = [value for value in candidates if value > centre + 1.5]
            if len(candidates) == 1:
                seen_rows.append(row)
                positions.append(candidates[0])
            elif len(candidates) > 1:
                ambiguous_rows.append(row)
        if ambiguous_rows:
            raise ValueError(f"{section['id']}: multiple dark strokes at {len(ambiguous_rows)} rows; the proposal utility cannot choose their meaning")
        if len(seen_rows) < .85 * (last - first + 1):
            raise ValueError(f"{section['id']}: insufficient distinct dark stroke for a proposal; inspect manually")
        missing = max(seen_rows[0] - first, last - seen_rows[-1], max(np.diff(seen_rows) - 1, default=0))
        if missing > 3:
            raise ValueError(f"{section['id']}: proposal would bridge {missing} unsupported rows; inspect manually")
        rows = np.arange(first, last + 1, dtype=float)
        x = np.interp(rows, seen_rows, positions)
        anchors = _coarse_anchors(rows, x, approximation_px)
        section["contour_selection"] = {"anchors_px": anchors, "half_width_px": float(half_width_px)}
        section["evidence"] = (str(section.get("evidence", "Caller-supplied calibration"))
                               + " Explicit AI/pixel-assisted dark-stroke corridor proposal; source pixels only, no benchmark labels or previous extracted curves; no human expert adjudication.")
        records.append({"section_id": section["id"], "anchor_count": len(anchors),
                        "source_rows_with_distinct_dark_stroke": len(seen_rows),
                        "proposal_missing_row_limit_px": 3, "observed_max_missing_rows": int(missing),
                        "anchors_px": anchors, "half_width_px": float(half_width_px)})
    out.mkdir(parents=True)
    shutil.copyfile(image_path, out / image_path.name)
    proposed["source"]["file"] = image_path.name
    proposed["vessel_id"] = str(proposed.get("vessel_id", "Assisted fixture")) + " — explicit pixel-assisted proposal"
    (out / "spec.json").write_text(json.dumps(proposed, indent=2, allow_nan=False) + "\n")
    # This overlay is diagnostic only. The inference input remains the unchanged
    # original source image, never the rendered proposal marks.
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for record in records:
        anchors = [tuple(p) for p in record["anchors_px"]]
        draw.line(anchors, fill=(0, 85, 200), width=1)
        for x, y in anchors:
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), outline=(0, 85, 200), width=1)
    overlay.save(out / "proposal-overlay.png")
    report = {"assistance_kind": "explicit_assistant_pixel_proposal", "proposal_status": "unvalidated_review_required",
              "human_expert_adjudication": False, "manual_click_count": 0,
              "method": "distinct_dark_pixel_runs_with_declared_axis_exclusion_and_coarse_pixel_anchor_approximation",
              "parameters": {"luminance_max": luminance_max, "proposal_approximation_px": approximation_px, "corridor_half_width_px": half_width_px},
              "source_sha256": hashlib.sha256(raw_source).hexdigest(),
              "parent_calibration_spec_sha256": hashlib.sha256(raw_spec).hexdigest(),
              "proposal_spec_sha256": hashlib.sha256((out / "spec.json").read_bytes()).hexdigest(),
              "proposal_implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "proposal_compute_seconds": time.perf_counter() - started,
              "source_inputs_read": [str(spec_path), str(image_path)],
              "labels_or_previous_output_curves_read": False,
              "section_count": len(records), "total_anchor_count": sum(r["anchor_count"] for r in records),
              "records": records,
              "limitations": ["Darkness chooses an assistant proposal, not engineering identity.",
                              "Corridors require explicit review and may still contain competing strokes; ordinary inference gates remain in force.",
                              "This opt-in assistance is not comparable to unassisted benchmark completion or unseen validation."]}
    (out / "assistance.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--luminance-max", type=float, default=128)
    parser.add_argument("--approximation-px", type=float, default=2.)
    parser.add_argument("--half-width-px", type=float, default=6.)
    args = parser.parse_args()
    result = propose(args.spec, args.out, luminance_max=args.luminance_max,
                     approximation_px=args.approximation_px, half_width_px=args.half_width_px)
    print(json.dumps({k: result[k] for k in ("section_count", "total_anchor_count", "proposal_compute_seconds", "proposal_status")}, indent=2))
